"""Fixture adapter: deterministic, explicitly NON-LEARNED and NON-QUALIFYING.

Why it exists
-------------
Package A needs a way to drive the real CPU media path -- decode, synthesis,
cadence expansion, streaming encode, decode validation and publish -- without a
model download, private artwork or GPU. This adapter provides that.

Why it can never qualify
------------------------
It produces intermediate frames by eased cross-dissolve between the two
bracketing anchors, plus a deterministic sub-pixel drift. MR-018 states
explicitly that "camera transforms, cross-fades, repeated source frames, stock
loops and pre-authored dense animation alone cannot satisfy this requirement".
The profile therefore declares ``engine_class=deterministic``,
``learned_temporal_participation=False`` and ``qualification_eligible=False``,
and the profile contract refuses to let those three disagree. Every manifest,
run record and benchmark report produced from it is labelled non-qualifying.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator

import numpy as np
from numpy.typing import NDArray

from animalite.adapters.base import AdapterContext
from animalite.contracts.assets import AnchorSet
from animalite.contracts.enums import EndpointControlMode, EngineClass, IssueSeverity, MotionTier
from animalite.contracts.media import OutputSpec
from animalite.contracts.profile import (
    Capabilities,
    EngineProfile,
    Resolution,
    ThreadBudget,
)
from animalite.contracts.validation import ValidationIssue
from animalite.errors import CodeVAL

__all__ = ["FIXTURE_ADAPTER_KEY", "FIXTURE_PROFILE", "NON_QUALIFYING_REASON", "FixtureAdapter"]

FIXTURE_ADAPTER_KEY = "fixture-synthetic"

NON_QUALIFYING_REASON = (
    "fixture adapter: deterministic eased cross-dissolve between approved anchors, "
    "with no learned component. MR-018 excludes cross-fades and repeated source "
    "frames from learned temporal capability, so no output from this adapter is "
    "evidence for AT-055/AT-056."
)

#: Controls the fixture adapter genuinely implements. Anything else is reported
#: as an explicit validation issue instead of being silently ignored.
_SUPPORTED_CONTROLS = ("ease", "drift_pixels")
_SUPPORTED_EASE = ("linear", "smoothstep")

FIXTURE_PROFILE = EngineProfile(
    profile_id="fixture-synthetic",
    display_name="Fixture synthetic anchor blend (NON-LEARNED, NON-QUALIFYING)",
    revision=1,
    adapter_key=FIXTURE_ADAPTER_KEY,
    engine_class=EngineClass.DETERMINISTIC,
    learned_temporal_participation=False,
    qualification_eligible=False,
    non_qualifying_reason=NON_QUALIFYING_REASON,
    supported_tiers=[MotionTier.E3],
    supported_tasks=["anchor_blend_fixture"],
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
    thread_budget=ThreadBudget(
        total_threads=4, python_threads=1, inference_threads=1, encoder_threads=2
    ),
    parameters={"ease": "smoothstep", "drift_pixels": 2.0},
    weights=[],
    binaries=[],
)


def _smoothstep(t: float) -> float:
    return t * t * (3.0 - 2.0 * t)


def _shift(frame: NDArray[np.uint8], dx: int, dy: int) -> NDArray[np.uint8]:
    """Integer-pixel roll with edge replication, so no wrapped content appears."""
    if dx == 0 and dy == 0:
        return frame
    out = np.roll(frame, shift=(dy, dx), axis=(0, 1))
    if dy > 0:
        out[:dy, :, :] = out[dy : dy + 1, :, :]
    elif dy < 0:
        out[dy:, :, :] = out[dy - 1 : dy, :, :]
    if dx > 0:
        out[:, :dx, :] = out[:, dx : dx + 1, :]
    elif dx < 0:
        out[:, dx:, :] = out[:, dx - 1 : dx, :]
    return out


class FixtureAdapter:
    """Deterministic anchor-blend adapter. Same output for the same inputs, always."""

    key = FIXTURE_ADAPTER_KEY

    def capabilities(self, profile: EngineProfile) -> Capabilities:
        return Capabilities(
            profile_id=profile.profile_id,
            adapter_key=self.key,
            engine_class=profile.engine_class,
            learned_temporal_participation=False,
            qualification_eligible=False,
            non_qualifying_reason=NON_QUALIFYING_REASON,
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
            notes=[
                "Deterministic: identical inputs and settings yield identical frames.",
                "No learned component; cannot satisfy MR-018 or AT-055/AT-056.",
                "Cancellation and the job deadline are checked between animation "
                "frames, so both take effect within one frame rather than instantly.",
            ],
        )

    def validate(
        self,
        profile: EngineProfile,
        anchors: AnchorSet,
        output: OutputSpec,
        controls: dict[str, float | int | str | bool],
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for name, value in controls.items():
            if name not in _SUPPORTED_CONTROLS:
                issues.append(
                    ValidationIssue(
                        code=CodeVAL.CONTROL_UNSUPPORTED,
                        severity=IssueSeverity.ERROR,
                        field_path=f"controls.{name}",
                        message=(f"the fixture adapter does not implement control {name!r}"),
                        remediation=(
                            "Remove the control or choose a profile whose capabilities() "
                            f"lists it. Supported: {', '.join(_SUPPORTED_CONTROLS)}."
                        ),
                    )
                )
            elif name == "ease" and value not in _SUPPORTED_EASE:
                issues.append(
                    ValidationIssue(
                        code=CodeVAL.CONTROL_UNSUPPORTED,
                        severity=IssueSeverity.ERROR,
                        field_path="controls.ease",
                        message=f"unsupported ease {value!r}",
                        remediation=f"Use one of: {', '.join(_SUPPORTED_EASE)}.",
                    )
                )
        issues.append(
            ValidationIssue(
                code=CodeVAL.NON_QUALIFYING_PROFILE,
                severity=IssueSeverity.WARNING,
                field_path="engine_profile_id",
                message=(
                    "fixture-synthetic is a non-learned fixture profile; its output is "
                    "not qualification evidence"
                ),
                remediation=(
                    "Use it for pipeline and harness verification only. AT-055/AT-056 "
                    "require a learned temporal profile on the D-02-approved host."
                ),
            )
        )
        return issues

    def synthesize(self, context: AdapterContext) -> Iterator[NDArray[np.uint8]]:
        """Yield one RGB24 frame per animation index, holding bounded memory.

        Only the two bracketing anchors are held at a time, so memory does not
        scale with clip length.
        """
        output = context.output
        anchors = context.anchors
        params = context.controls
        ease = str(params.get("ease", "smoothstep"))
        drift = float(params.get("drift_pixels", 0.0))
        indices = anchors.indices
        cancel = context.cancel_requested

        for frame_index in range(output.animation_frame_count):
            if isinstance(cancel, threading.Event) and cancel.is_set():
                return
            left_pos = max(i for i, idx in enumerate(indices) if idx <= frame_index)
            if indices[left_pos] == frame_index:
                # An approved anchor is reproduced exactly at its own index.
                yield np.ascontiguousarray(context.anchor_frames[frame_index])
                continue
            right_pos = min(i for i, idx in enumerate(indices) if idx > frame_index)
            left_idx, right_idx = indices[left_pos], indices[right_pos]
            span = right_idx - left_idx
            t = (frame_index - left_idx) / span
            weight = _smoothstep(t) if ease == "smoothstep" else t

            left = context.anchor_frames[left_idx].astype(np.float32)
            right = context.anchor_frames[right_idx].astype(np.float32)
            blended = left * (1.0 - weight) + right * weight
            frame = np.clip(np.rint(blended), 0, 255).astype(np.uint8)

            if drift:
                # Deterministic lateral drift peaking mid-interval: makes the
                # intermediates differ from a pure dissolve without pretending
                # to be motion estimation.
                offset = round(drift * float(np.sin(np.pi * t)))
                frame = _shift(frame, offset, 0)
            yield np.ascontiguousarray(frame)
