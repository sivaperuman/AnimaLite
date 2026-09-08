"""RIFE/ncnn CPU adapter: the first learned temporal component (MR-018).

This is a **learned** adapter. Unlike the fixture adapter it declares
``learned_temporal_participation=True`` and is therefore qualification-eligible
in principle -- the benchmark evaluator still refuses a pass without an approved
host, a locked sample and human quality evidence.

Design notes that are load-bearing, each backed by a measurement recorded in
``docs/decisions/DEC-0012-rife-invocation-strategy.md``:

*Explicit per-frame timestep.* The upstream tool also has a directory mode
(``-i``/``-n``) that is far cheaper because it loads the model once. It is not
used, because ``-n`` performs recursive 2x doubling rather than uniform
sampling: asking for 72 frames from two anchors produced motion that completed
by frame ~37 and then froze on the end anchor, deviating up to 20.15 px from a
linear ramp. That would silently corrupt the section 12.0 frame-index contract
and the source/synthesized/duplicated accounting. Per-frame ``-s`` measured
2.60 px deviation on the same clip.

*The cost is counted, not hidden.* One subprocess per synthesized frame means
the model is reloaded every frame. Handoff section 5: "If a candidate CLI loads
weights for every invocation, count that cost." The whole loop runs inside the
``temporal_synthesis`` stage, so it is inside the section 12.0 warm boundary.
:meth:`RifeNcnnAdapter.synthesize` additionally records the invocation count and
subprocess wall time as notes on the context.

*Anchors are reproduced exactly.* An approved frame at its own animation index
is emitted from the decoded source, never round-tripped through the model.
"""

from __future__ import annotations

import subprocess
import threading
import time
from collections.abc import Iterator, Mapping
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from animalite.adapters.base import AdapterContext
from animalite.adapters.rife_runtime import PINNED_MODELS, RIFE_RELEASE, RifeRuntime
from animalite.contracts.assets import AnchorSet
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
from animalite.errors import AdapterError, CodeVAL
from animalite.media.decode import decode_image_rgb24
from animalite.media.ffmpeg import FFmpegTools
from animalite.media.image import write_png_rgb24

__all__ = ["RIFE_ADAPTER_KEY", "RIFE_PROFILE", "RifeNcnnAdapter"]

RIFE_ADAPTER_KEY = "rife-ncnn"

DEFAULT_MODEL = "rife-v4.6"

_SUPPORTED_CONTROLS = ("model", "tta_spatial")

#: Markers the upstream binary prints when Vulkan cannot be initialised. Their
#: presence is positive evidence that no GPU was used; their absence is not
#: evidence that one was.
_VULKAN_FAILURE_MARKERS = ("vkCreateInstance failed", "vkEnumeratePhysicalDevices failed")


def _license_evaluation() -> LicenseEvaluationRef:
    """The recorded, deliberately unresolved licence position (CR-024).

    Code and weights are both stated MIT upstream, and the weight statement is
    explicit and separate from the code licence -- which is what MR-012 asks
    for. What is *not* resolved is that the ncnn-format weights shipped in the
    release are conversions, and that repository does not restate weight terms.
    So the mapping stays ``unresolved`` / ``use_eligible=False`` /
    ``resolvable`` until the D-06 reviewer signs it off, rather than being
    asserted as cleared on an implementer's reading of two repositories.
    """
    return LicenseEvaluationRef(
        evaluation_id="license-eval:rife-ncnn-20221029",
        subject="rife-ncnn-vulkan 20221029 (MIT code, BSD-3 ncnn) + RIFE v4.6 weights",
        policy_state="pending",
        use_eligible=False,
        eligibility_block_kind="resolvable",
        reviewer=None,
        evidence_url="https://github.com/hzwer/Practical-RIFE#trained-model",
    )


RIFE_PROFILE = EngineProfile(
    profile_id="rife-ncnn-v4.6-cpu",
    display_name="RIFE v4.6 via ncnn, CPU-only (learned temporal interpolation)",
    revision=1,
    adapter_key=RIFE_ADAPTER_KEY,
    engine_class=EngineClass.ML_ASSISTED,
    learned_temporal_participation=True,
    qualification_eligible=True,
    non_qualifying_reason=None,
    supported_tiers=[MotionTier.E3],
    supported_tasks=["temporal_interpolation"],
    supported_controls=list(_SUPPORTED_CONTROLS),
    supported_endpoint_modes=[EndpointControlMode.DETERMINISTIC_STATE],
    supported_resolutions=[
        Resolution(width=640, height=360),
        Resolution(width=320, height=180),
    ],
    min_anchor_count=2,
    max_anchor_count=4,
    max_animation_frame_count=72,
    cpu_only_guaranteed=True,
    # 4 threads total on the P-L envelope: 1 for Python, 2 for ncnn inference,
    # 1 reserved for the encoder, which runs after synthesis rather than beside it.
    thread_budget=ThreadBudget(
        total_threads=4, python_threads=1, inference_threads=2, encoder_threads=1
    ),
    parameters={"model": DEFAULT_MODEL, "tta_spatial": False},
    weights=[
        ArtifactIdentity(
            kind="weights",
            identifier=f"{DEFAULT_MODEL}/{name}",
            version="20221029",
            content_hash=f"sha256:{digest}",
            source_url=str(RIFE_RELEASE["source_url"]),
            license_id="MIT (upstream RIFE trained models; see docs/licensing.md)",
            notes="ncnn-format conversion shipped in the pinned release",
        )
        for name, digest in sorted(PINNED_MODELS[DEFAULT_MODEL].file_hashes.items())
    ],
    binaries=[
        ArtifactIdentity(
            kind="binary",
            identifier="rife-ncnn-vulkan",
            version=str(RIFE_RELEASE["version"]),
            content_hash=f"sha256:{RIFE_RELEASE['binary_sha256']}",
            source_url=str(RIFE_RELEASE["source_url"]),
            license_id="MIT (wrapper) + BSD-3-Clause (ncnn)",
            notes="Invoked with -g -1 (CPU). Links libvulkan but needs no GPU.",
        )
    ],
    license_evaluation=_license_evaluation(),
)


class RifeNcnnAdapter:
    """Drives the pinned rife-ncnn-vulkan executable, CPU-only."""

    key = RIFE_ADAPTER_KEY

    def __init__(
        self,
        runtime: RifeRuntime | None = None,
        tools: FFmpegTools | None = None,
    ) -> None:
        self._runtime = runtime
        self._tools = tools

    # ------------------------------------------------------------------ helpers

    @property
    def runtime(self) -> RifeRuntime:
        if self._runtime is None:
            self._runtime = RifeRuntime.discover()
        return self._runtime

    @property
    def tools(self) -> FFmpegTools:
        if self._tools is None:
            self._tools = FFmpegTools.discover()
        return self._tools

    @staticmethod
    def _model_name(profile: EngineProfile, controls: Mapping[str, object]) -> str:
        return str(controls.get("model", profile.parameters.get("model", DEFAULT_MODEL)))

    @staticmethod
    def _required_timesteps(anchors: AnchorSet, output: OutputSpec) -> list[float]:
        """Timesteps the request will actually ask the model for."""
        indices = anchors.indices
        steps: list[float] = []
        for frame_index in range(output.animation_frame_count):
            if frame_index in indices:
                continue
            left = max(i for i in indices if i <= frame_index)
            right = min(i for i in indices if i > frame_index)
            steps.append((frame_index - left) / (right - left))
        return steps

    # -------------------------------------------------------------- section 6.3

    def capabilities(self, profile: EngineProfile) -> Capabilities:
        model = PINNED_MODELS.get(self._model_name(profile, {}))
        runtime = self.runtime
        notes = [
            "Learned temporal interpolation: the model estimates flow between "
            "two approved anchors and synthesizes the intermediate frame.",
            "CPU-only: invoked with -g -1. The binary links libvulkan and "
            "attempts instance creation at startup regardless; a failure there "
            "is recorded as positive evidence that no GPU was used.",
            "One subprocess per synthesized frame, so the model is reloaded per "
            "frame. That cost is inside the timed synthesis stage and is "
            "reported, not subtracted (handoff section 5).",
            "Cancellation and the job deadline are checked between frames.",
        ]
        if model is not None and not model.supports_arbitrary_timestep:
            notes.append(
                f"{model.name} is midpoint-only and is rejected for any timestep other than 0.5."
            )
        if not runtime.available:
            notes.append(
                "Runtime NOT INSTALLED on this host: no weights or executable "
                "resolved. Validation will reject execution."
            )
        return Capabilities(
            profile_id=profile.profile_id,
            adapter_key=self.key,
            engine_class=profile.engine_class,
            learned_temporal_participation=True,
            qualification_eligible=profile.qualification_eligible,
            non_qualifying_reason=profile.non_qualifying_reason,
            supported_tiers=list(profile.supported_tiers),
            supported_tasks=list(profile.supported_tasks),
            supported_controls=list(_SUPPORTED_CONTROLS),
            supported_endpoint_modes=list(profile.supported_endpoint_modes),
            supported_resolutions=list(profile.supported_resolutions),
            min_anchor_count=profile.min_anchor_count,
            max_anchor_count=profile.max_anchor_count,
            max_animation_frame_count=profile.max_animation_frame_count,
            cpu_only_guaranteed=True,
            supports_safe_cancel=True,
            notes=notes,
        )

    def validate(
        self,
        profile: EngineProfile,
        anchors: AnchorSet,
        output: OutputSpec,
        controls: dict[str, float | int | str | bool],
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []

        for name in controls:
            if name not in _SUPPORTED_CONTROLS:
                issues.append(
                    ValidationIssue(
                        code=CodeVAL.CONTROL_UNSUPPORTED,
                        severity=IssueSeverity.ERROR,
                        field_path=f"controls.{name}",
                        message=f"the RIFE adapter does not implement control {name!r}",
                        remediation=(
                            f"Remove the control. Supported: {', '.join(_SUPPORTED_CONTROLS)}."
                        ),
                    )
                )

        model_name = self._model_name(profile, controls)
        model = PINNED_MODELS.get(model_name)
        if model is None:
            issues.append(
                ValidationIssue(
                    code=CodeVAL.RUNTIME_MODEL_UNKNOWN,
                    severity=IssueSeverity.ERROR,
                    field_path="controls.model",
                    message=f"model {model_name!r} is not pinned",
                    remediation=(
                        f"Use a pinned model: {', '.join(sorted(PINNED_MODELS))}. "
                        "An unpinned checkpoint has no verified digest."
                    ),
                )
            )
            return issues

        # The rule that stops a silently-wrong result: a midpoint-only model
        # asked for any other timestep returns a plausible but temporally
        # incorrect frame.
        if not model.supports_arbitrary_timestep:
            needed = {round(t, 6) for t in self._required_timesteps(anchors, output)}
            off_midpoint = sorted(t for t in needed if abs(t - 0.5) > 1e-9)
            if off_midpoint:
                issues.append(
                    ValidationIssue(
                        code=CodeVAL.RUNTIME_TIMESTEP_UNSUPPORTED,
                        severity=IssueSeverity.ERROR,
                        field_path="controls.model",
                        message=(
                            f"model {model_name!r} ({model.architecture}) is "
                            f"midpoint-only, but this request needs "
                            f"{len(off_midpoint)} non-0.5 timestep(s), e.g. "
                            f"{off_midpoint[:3]}. It would return plausible but "
                            "temporally wrong frames rather than failing."
                        ),
                        remediation=("Use rife-v4.6, which honours an arbitrary timestep."),
                    )
                )

        runtime = self.runtime
        verification = runtime.verify(model_name)
        if not verification.usable:
            for problem in verification.problems:
                issues.append(
                    ValidationIssue(
                        code=CodeVAL.RUNTIME_UNVERIFIED,
                        severity=IssueSeverity.ERROR,
                        field_path="environment.rife_runtime",
                        message=problem,
                        remediation=(
                            "Install the pinned release with `animalite runtime "
                            "fetch`, or point ANIMALITE_RIFE_BIN / "
                            "ANIMALITE_RIFE_MODELS at a verified install."
                        ),
                    )
                )

        evaluation = profile.license_evaluation
        if evaluation is not None and not evaluation.use_eligible:
            issues.append(
                ValidationIssue(
                    code=CodeVAL.LICENCE_NOT_CLEARED,
                    severity=IssueSeverity.WARNING,
                    field_path="profile.license_evaluation",
                    message=(
                        f"licence evaluation {evaluation.evaluation_id} is "
                        f"{evaluation.policy_state!r} with use_eligible=False "
                        f"({evaluation.eligibility_block_kind})"
                    ),
                    remediation=(
                        "Development and benchmarking may proceed. Production use "
                        "requires the recorded review and approved use case (C-04); "
                        "the benchmark evaluator blocks qualification until then."
                    ),
                )
            )
        return issues

    # ------------------------------------------------------------------ synthesis

    def synthesize(self, context: AdapterContext) -> Iterator[NDArray[np.uint8]]:
        output = context.output
        anchors = context.anchors
        indices = anchors.indices
        controls: dict[str, object] = dict(context.profile.parameters)
        model_name = self._model_name(context.profile, controls)
        model = PINNED_MODELS[model_name]

        runtime = self.runtime
        verification = runtime.verify(model_name)
        if not verification.usable:
            raise AdapterError("RIFE runtime is not usable: " + "; ".join(verification.problems))
        binary = runtime.binary_path
        model_dir = runtime.model_dir(model_name)
        if binary is None or model_dir is None:  # pragma: no cover - verify() covers it
            raise AdapterError("RIFE runtime resolved inconsistently")

        scratch = context.scratch_dir / "rife"
        scratch.mkdir(parents=True, exist_ok=True)

        # Normalized anchors on disk: the runtime's interface is file-based, and
        # these are the exact pixels the model sees.
        anchor_paths: dict[int, Path] = {}
        for index in indices:
            path = scratch / f"anchor_{index:04d}.png"
            write_png_rgb24(self.tools, context.anchor_frames[index], path)
            anchor_paths[index] = path

        threads = max(1, context.profile.thread_budget.inference_threads)
        cancel = context.cancel_requested
        invocations = 0
        subprocess_seconds = 0.0
        vulkan_failed = False
        first_stderr = ""

        for frame_index in range(output.animation_frame_count):
            if isinstance(cancel, threading.Event) and cancel.is_set():
                return

            if frame_index in indices:
                # An approved anchor is emitted exactly, never re-synthesized.
                yield np.ascontiguousarray(context.anchor_frames[frame_index])
                continue

            left = max(i for i in indices if i <= frame_index)
            right = min(i for i in indices if i > frame_index)
            timestep = (frame_index - left) / (right - left)
            destination = scratch / f"synth_{frame_index:04d}.png"

            argv = [
                str(binary),
                "-0",
                str(anchor_paths[left]),
                "-1",
                str(anchor_paths[right]),
                "-o",
                str(destination),
                "-m",
                str(model_dir),
                "-s",
                f"{timestep:.8f}",
                "-g",
                "-1",  # CPU. Never 'auto'.
                "-j",
                f"1:{threads}:1",
            ]
            if controls.get("tta_spatial"):
                argv.append("-x")

            started = time.perf_counter()
            try:
                completed = subprocess.run(  # noqa: S603 - argv list, no shell
                    argv, capture_output=True, timeout=600.0, check=False
                )
            except subprocess.TimeoutExpired as exc:
                raise AdapterError(
                    f"RIFE timed out synthesizing animation frame {frame_index}"
                ) from exc
            subprocess_seconds += time.perf_counter() - started
            invocations += 1

            stderr_text = completed.stderr.decode("utf-8", "replace")
            if invocations == 1:
                first_stderr = stderr_text.strip()
            if any(marker in stderr_text for marker in _VULKAN_FAILURE_MARKERS):
                vulkan_failed = True

            if completed.returncode != 0 or not destination.is_file():
                raise AdapterError(
                    f"RIFE failed on animation frame {frame_index} "
                    f"(t={timestep:.6f}): exit {completed.returncode}; "
                    f"{stderr_text.strip()[-500:]}"
                )

            frame = decode_image_rgb24(
                self.tools, destination, width=output.width, height=output.height
            )
            # Reclaim scratch as we go: a 72-frame clip would otherwise leave
            # ~70 full-resolution PNGs behind for every attempt.
            destination.unlink(missing_ok=True)
            yield frame

        context.device_evidence = self._device_evidence(vulkan_failed, first_stderr, model_name)
        context.notes.extend(
            [
                f"rife model={model_name} ({model.architecture}) invocations={invocations}",
                f"rife subprocess wall={subprocess_seconds:.3f}s "
                f"({subprocess_seconds / max(1, invocations):.3f}s per synthesized frame, "
                "including one model load each)",
            ]
        )

    @staticmethod
    def _device_evidence(vulkan_failed: bool, first_stderr: str, model_name: str) -> DeviceEvidence:
        notes = [
            "Inference invoked with -g -1, which selects ncnn's CPU path "
            "explicitly. Automatic device selection is never used.",
            f"Encoder runs separately on the CPU; model={model_name}.",
        ]
        if vulkan_failed:
            notes.append(
                "Positive evidence: the runtime could not create a Vulkan "
                "instance on this host, so a GPU path was unavailable, not "
                f"merely unselected. First stderr: {first_stderr[:200]!r}"
            )
        else:
            notes.append(
                "No Vulkan initialisation failure was observed. -g -1 still "
                "selects the CPU path, but absence of that message is not by "
                "itself proof that no accelerator existed."
            )
        return DeviceEvidence(
            inference_device_status=EvidenceStatus.MEASURED,
            inference_device="cpu",
            encoder_device="cpu",
            hardware_acceleration_requested=False,
            network_calls_observed_status=EvidenceStatus.PENDING,
            notes=notes,
        )
