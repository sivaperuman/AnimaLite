"""One supervised CPU adapter: a timed LTX draft followed by Wan VACE refinement."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from numpy.typing import NDArray
from pydantic import ConfigDict, Field, ValidationError

from animalite.adapters.base import AdapterContext
from animalite.adapters.ltx_wan_bundle import ModelBundle, configured_bundle
from animalite.admission import evaluate_admission
from animalite.contracts.assets import AnchorSet
from animalite.contracts.base import Contract, sha256_file
from animalite.contracts.enums import (
    EndpointControlMode,
    EngineClass,
    EvidenceStatus,
    IssueSeverity,
    MotionTier,
)
from animalite.contracts.media import OutputSpec
from animalite.contracts.profile import (
    ArtifactIdentity,
    Capabilities,
    EngineProfile,
    LicenseEvaluationRef,
    Resolution,
    ThreadBudget,
)
from animalite.contracts.results import DeviceEvidence
from animalite.contracts.validation import ValidationIssue
from animalite.errors import (
    AdapterError,
    AdmissionDenied,
    CleanupFailed,
    CodeVAL,
    JobCancelled,
    JobTimeoutError,
    ValidationRejected,
)
from animalite.proc import ProcessCancelled, ProcessTimeout, run_capture
from animalite.resources import apply_thread_environment

PROFILE_ID = "ltx-wan-cpu"


class InferenceControls(Contract):
    model_config = ConfigDict(strict=True)
    seed: int = Field(default=0, ge=0, le=2**32 - 1)
    ltx_steps: int = Field(default=30, ge=1, le=100)
    wan_steps: int = Field(default=30, ge=1, le=100)
    motion_strength: float = Field(default=0.5, ge=0, le=1)
    wan_conditioning_scale: float = Field(default=1, gt=0, le=3)


def model_profile(bundle: ModelBundle | None) -> EngineProfile:
    weights = [
        ArtifactIdentity(
            kind="weights", identifier=key, content_hash=snapshot.digest if snapshot else None
        )
        for key, snapshot in (
            ("ltx", bundle.ltx if bundle else None),
            ("wan", bundle.wan if bundle else None),
        )
    ]
    return EngineProfile(
        profile_id=PROFILE_ID,
        adapter_key=PROFILE_ID,
        display_name="LTX-Video and Wan VACE (CPU research)",
        engine_class=EngineClass.GENERATIVE,
        learned_temporal_participation=True,
        qualification_eligible=False,
        non_qualifying_reason="Pretrained quality and target CPU performance are unmeasured.",
        supported_tiers=[MotionTier.E3],
        supported_tasks=["conditioned_video"],
        supported_controls=list(InferenceControls.model_fields),
        supported_endpoint_modes=[EndpointControlMode.DETERMINISTIC_STATE],
        supported_resolutions=[
            Resolution(width=w, height=h)
            for w, h in ((320, 180), (640, 360), (144, 256), (180, 320), (360, 640))
        ],
        thread_budget=ThreadBudget(
            total_threads=4, python_threads=1, inference_threads=2, encoder_threads=1
        ),
        parameters=InferenceControls().model_dump(),
        weights=weights,
        license_evaluation=LicenseEvaluationRef(
            evaluation_id="ltx-wan-local-snapshots",
            subject="Diffusers LTX-Video and Wan VACE snapshots selected for this run",
            evidence_url="THIRD_PARTY_NOTICES.md",
        ),
    )


def _run(context: AdapterContext, args: list[str]) -> None:
    env = apply_thread_environment(context.profile.thread_budget)
    env.update(
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        CUDA_VISIBLE_DEVICES="",
        TOKENIZERS_PARALLELISM="false",
    )
    try:
        result = run_capture(
            args, env=env, cancel=context.cancel, timeout=context.remaining_seconds()
        )
    except ProcessCancelled as exc:
        raise JobCancelled(
            "cancelled during neural video generation", survivors=exc.survivors
        ) from exc
    except ProcessTimeout as exc:
        raise JobTimeoutError(
            "deadline expired during neural video generation", survivors=exc.survivors
        ) from exc
    if result.survivors:
        raise CleanupFailed("neural video worker cleanup failed", survivors=result.survivors)
    if result.returncode:
        raise AdapterError(
            result.stderr[-2500:].decode(errors="replace") or "neural video worker failed"
        )


def _conditioning_media(context: AdapterContext, folder: Path) -> dict[str, str]:
    media: dict[str, str] = {}
    output = context.output
    for name, asset in context.conditioning.assets().items() if context.conditioning else ():
        video = name.endswith("video")
        # Snapshot the input that FFmpeg actually consumes, including its digest.
        source = folder / (name + (".mp4" if video else ".png"))
        shutil.copyfile(asset.path, source)
        if sha256_file(str(source)) != asset.content_hash:
            raise AdapterError(f"conditioning asset changed: {name}")
        n = output.animation_frame_count if video else 1
        target = folder / (name + ".rgb")
        fit = (
            f"scale={output.width}:{output.height}:force_original_aspect_ratio=decrease,"
            f"pad={output.width}:{output.height}:(ow-iw)/2:(oh-ih)/2,setsar=1"
        )
        filters = (f"fps={output.cadence.animation_fps}," if video else "") + fit
        fmt = ["-f", "mov"] if video else ["-f", "image2", "-pattern_type", "none", "-c:v", "png"]
        _run(
            context,
            [
                context.tools.ffmpeg_path,
                "-nostdin",
                "-v",
                "error",
                "-protocol_whitelist",
                "file",
                "-threads",
                "1",
                *fmt,
                "-i",
                str(source),
                "-map",
                "0:v:0",
                "-filter_threads",
                "1",
                "-vf",
                filters,
                "-frames:v",
                str(n),
                "-threads",
                "1",
                "-pix_fmt",
                "rgb24",
                "-f",
                "rawvideo",
                str(target),
            ],
        )
        if target.stat().st_size != n * output.width * output.height * 3:
            raise AdapterError(f"{name} does not cover all {n} requested animation frames")
        media[name] = str(target)
    return media


class LtxWanAdapter:
    key = PROFILE_ID

    def __init__(self) -> None:
        self.configuration_error = ""
        try:
            self.bundle = configured_bundle()
        except (OSError, ValueError, ValidationRejected) as exc:
            self.bundle = None
            self.configuration_error = str(exc)

    def capabilities(self, profile: EngineProfile) -> Capabilities:
        fields = set(Capabilities.model_fields) & set(EngineProfile.model_fields)
        return Capabilities(
            **profile.model_dump(include=fields),
            supports_safe_cancel=True,
            notes=["Explicit CPU inference, local Diffusers snapshots, no automatic download."],
        )

    def validate(
        self,
        profile: EngineProfile,
        anchors: AnchorSet,
        output: OutputSpec,
        controls: dict[str, float | int | str | bool],
    ) -> list[ValidationIssue]:
        problems = []
        bundle = self.bundle
        if (
            not bundle
            or profile.weights != model_profile(bundle).weights
            or not profile.learned_temporal_participation
            or profile.profile_id != PROFILE_ID
        ):
            problems.append(
                (
                    CodeVAL.RUNTIME_UNVERIFIED,
                    self.configuration_error or "Select a pinned bundle matching this profile.",
                )
            )
        if any(
            importlib.util.find_spec(name) is None
            for name in (
                "torch",
                "diffusers",
                "transformers",
                "accelerate",
                "sentencepiece",
                "ftfy",
                "torchvision",
            )
        ):
            problems.append(
                (
                    CodeVAL.RUNTIME_UNVERIFIED,
                    "Install the neural optional dependencies in the same Python environment.",
                )
            )
        try:
            InferenceControls.model_validate(controls)
        except ValidationError as exc:
            problems.append((CodeVAL.CONTROL_VALUE_INVALID, str(exc)))
        return [
            ValidationIssue(
                code=code,
                severity=IssueSeverity.ERROR,
                field_path="ltx-wan-cpu",
                message=msg,
                remediation="See the LTX and Wan instructions in README.md.",
            )
            for code, msg in problems
        ]

    def synthesize(self, context: AdapterContext) -> Iterator[NDArray[np.uint8]]:
        bundle = self.bundle
        if (
            not bundle
            or context.profile.weights != model_profile(bundle).weights
            or context.profile.profile_id != PROFILE_ID
            or not context.profile.learned_temporal_participation
        ):
            raise AdapterError("local model snapshots do not match the pinned learned profile")
        admission = evaluate_admission(context.profile, context.purpose)
        if not admission.admitted:
            raise AdmissionDenied("; ".join(admission.reasons))
        controls = InferenceControls.model_validate(context.effective_controls())
        folder = (context.scratch_dir / "ltx-wan").resolve()
        folder.mkdir()
        for index, frame in context.anchor_frames.items():
            np.save(folder / f"anchor-{index}.npy", frame, allow_pickle=False)
        media = _conditioning_media(context, folder)
        output = context.output
        plan = {
            "bundle": bundle.model_dump(mode="json"),
            "purpose": context.purpose.value,
            "controls": controls.model_dump(),
            "media": media,
            "width": output.width,
            "height": output.height,
            "frames": output.animation_frame_count,
            "fps": output.cadence.animation_fps,
            "indices": sorted(context.anchor_frames),
            "strengths": context.conditioning.anchor_strengths if context.conditioning else {},
            "prompt": context.shot.motion_description if context.shot else "",
            "negative_prompt": ", ".join(context.shot.negative_constraints) if context.shot else "",
            "threads": context.profile.thread_budget.inference_threads,
        }
        # The supervisor also removes verified checkpoint copies if it kills the worker.
        with TemporaryDirectory(dir=folder, prefix="snapshots-") as snapshots:
            plan["snapshot_scratch"] = snapshots
            (folder / "plan.json").write_text(json.dumps(plan))
            _run(context, [sys.executable, "-m", "animalite.adapters.ltx_wan_worker", str(folder)])
        frames = np.load(folder / "frames.npy", mmap_mode="r", allow_pickle=False)
        if frames.dtype != np.uint8 or frames.shape != (
            output.animation_frame_count,
            output.height,
            output.width,
            3,
        ):
            raise AdapterError("neural worker returned unexpected frame geometry")
        context.device_evidence = DeviceEvidence(
            inference_device_status=EvidenceStatus.MEASURED,
            inference_device="cpu",
            notes=["Worker verified CPU parameter devices for both pipelines."],
        )
        context.notes.append(
            "LTX draft and Wan VACE refinement completed. Approved anchors copied exactly."
        )
        for i, frame in enumerate(frames):
            yield context.anchor_frames.get(i, frame)
