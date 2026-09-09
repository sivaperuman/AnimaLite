"""The classical warp/flow comparator.

Requirements §6.0: "Evaluate a classical warp/flow baseline and one pinned
RIFE/ncnn CPU candidate first." This is that baseline, and its job is to be
*beaten*, not to pass.

Why a comparator earns its place. A test the learned candidate passes is only
evidence of learned temporal capability if a non-learned method fails it. The
PR-1 review made exactly this point about the disc test: a classical motion
algorithm could also pass it, so passing alone certifies nothing. Running this
adapter over the same clips answers "would a baseline have done this too?" with
a measurement instead of an assumption.

It cannot itself qualify, and not merely by declaration: MR-018 requires the
learned component to participate in temporal synthesis, and there is no learned
component here at all. ``EngineProfile`` refuses ``qualification_eligible=True``
without ``learned_temporal_participation``, so the profile below could not be
marked eligible even by editing this file.

Cost note: flow is estimated **once per anchor pair**, not once per frame. A
72-frame clip from two anchors runs the search twice and then pays only two
warps and a blend per frame.
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
from animalite.errors import AdapterError, CodeVAL
from animalite.media.flow import (
    DEFAULT_ACCEPT_MARGIN,
    DEFAULT_BLOCK_SIZE,
    DEFAULT_SEARCH_RADIUS,
    estimate_block_flow,
    interpolate_motion_compensated,
)

__all__ = [
    "CLASSICAL_ADAPTER_KEY",
    "CLASSICAL_WARP_PROFILE",
    "NON_QUALIFYING_REASON",
    "ClassicalWarpAdapter",
]

CLASSICAL_ADAPTER_KEY = "classical-warp"

NON_QUALIFYING_REASON = (
    "classical comparator: block-matching motion estimation with bilinear "
    "warping and a time-weighted blend, with no learned component of any kind. "
    "MR-018 requires the learned component to participate in temporal synthesis, "
    "so no output from this adapter is evidence for AT-055/AT-056. It exists to "
    "establish what a non-learned baseline already achieves on the same clips."
)

_SUPPORTED_CONTROLS = ("block_size", "search_radius", "accept_margin")

#: Bounds are engineering limits, not tuned thresholds. Block size need NOT
#: divide the output: 16 does not divide 360, and the estimator covers whole
#: blocks while the remainder strip inherits the nearest block's flow. It only
#: has to fit. The search radius is bounded because full search is quadratic in
#: it and an unbounded value would silently make a run untimeable.
_BLOCK_SIZES = (8, 16, 32)
_MAX_SEARCH_RADIUS = 64


def _coerce_numeric(value: float | int | str | bool, field: str) -> float:
    """Reject a control that is not a plain finite number.

    ``bool`` is rejected explicitly: it is an ``int`` subclass, and ``True`` as a
    search radius is a mistake rather than a radius of one.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AdapterError(f"{field} must be a number, got {value!r}")
    numeric = float(value)
    if not np.isfinite(numeric):
        raise AdapterError(f"{field} must be finite, got {value!r}")
    return numeric


def _validate_controls(
    controls: dict[str, float | int | str | bool], output: OutputSpec
) -> list[ValidationIssue]:
    """Check the resolved control values before any decoding or synthesis."""
    issues: list[ValidationIssue] = []

    def invalid(field: str, message: str, remediation: str) -> ValidationIssue:
        return ValidationIssue(
            code=CodeVAL.CONTROL_VALUE_INVALID,
            severity=IssueSeverity.ERROR,
            field_path=f"controls.{field}",
            message=message,
            remediation=remediation,
        )

    for name, value in controls.items():
        if name not in _SUPPORTED_CONTROLS:
            issues.append(
                ValidationIssue(
                    code=CodeVAL.CONTROL_UNSUPPORTED,
                    severity=IssueSeverity.ERROR,
                    field_path=f"controls.{name}",
                    message=f"the classical comparator does not implement control {name!r}",
                    remediation=(
                        "Remove the control or choose a profile whose capabilities() "
                        f"lists it. Supported: {', '.join(_SUPPORTED_CONTROLS)}."
                    ),
                )
            )
            continue
        try:
            numeric = _coerce_numeric(value, name)
        except AdapterError as exc:
            issues.append(invalid(name, str(exc), f"Pass a finite number for {name!r}."))
            continue

        if name == "block_size":
            if numeric not in _BLOCK_SIZES:
                issues.append(
                    invalid(
                        name,
                        f"block_size {value!r} is not one of {_BLOCK_SIZES}",
                        f"Use one of: {', '.join(str(b) for b in _BLOCK_SIZES)}.",
                    )
                )
            elif output.width < numeric or output.height < numeric:
                issues.append(
                    invalid(
                        name,
                        f"block_size {int(numeric)} exceeds the "
                        f"{output.width}x{output.height} output, leaving no whole block",
                        "Choose a block size no larger than the smaller output dimension.",
                    )
                )
        elif name == "search_radius":
            if numeric < 0 or numeric > _MAX_SEARCH_RADIUS:
                issues.append(
                    invalid(
                        name,
                        f"search_radius {numeric} lies outside 0..{_MAX_SEARCH_RADIUS}",
                        f"Full search is quadratic in the radius; keep it within "
                        f"0..{_MAX_SEARCH_RADIUS} so a run stays timeable.",
                    )
                )
        elif name == "accept_margin" and numeric < 0:
            issues.append(
                invalid(
                    name,
                    f"accept_margin {numeric} is negative, which would accept "
                    "displacements that match worse than standing still",
                    "Use zero or a positive mean-absolute-difference margin.",
                )
            )
    return issues


CLASSICAL_WARP_PROFILE = EngineProfile(
    profile_id="classical-warp-baseline",
    display_name="Classical block-matching warp comparator (NON-LEARNED, NON-QUALIFYING)",
    revision=1,
    adapter_key=CLASSICAL_ADAPTER_KEY,
    engine_class=EngineClass.DETERMINISTIC,
    learned_temporal_participation=False,
    qualification_eligible=False,
    non_qualifying_reason=NON_QUALIFYING_REASON,
    supported_tiers=[MotionTier.E3],
    supported_tasks=["temporal_interpolation_baseline"],
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
    # Pure NumPy on one thread: the comparator must not win on parallelism the
    # learned candidate is not also given.
    thread_budget=ThreadBudget(
        total_threads=4, python_threads=1, inference_threads=1, encoder_threads=2
    ),
    parameters={
        "block_size": DEFAULT_BLOCK_SIZE,
        "search_radius": DEFAULT_SEARCH_RADIUS,
        "accept_margin": DEFAULT_ACCEPT_MARGIN,
    },
    weights=[],
    binaries=[],
)


class ClassicalWarpAdapter:
    """Motion-compensated interpolation with no learned component."""

    key = CLASSICAL_ADAPTER_KEY

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
                "Exists as the control for the learned candidate: a test this "
                "adapter also passes is not evidence of learned capability.",
                "Motion beyond the search radius is not found; the estimator "
                "reports no motion rather than a confident wrong displacement.",
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
        """Validate the resolved configuration, then warn about what it is."""
        issues = _validate_controls(controls, output)
        issues.append(
            ValidationIssue(
                code=CodeVAL.NON_QUALIFYING_PROFILE,
                severity=IssueSeverity.WARNING,
                field_path="engine_profile_id",
                message=(
                    "classical-warp-baseline is a non-learned comparator; its output "
                    "is a baseline to measure against, never qualification evidence"
                ),
                remediation=(
                    "Run it alongside the learned profile to show what a non-learned "
                    "method already achieves. AT-055/AT-056 require a learned "
                    "temporal profile on the D-02-approved host."
                ),
            )
        )
        return issues

    def synthesize(self, context: AdapterContext) -> Iterator[NDArray[np.uint8]]:
        """Yield one RGB24 animation frame per index, bounded in memory.

        Flow is estimated once per anchor pair and cached for the segment, so a
        long clip does not repeat the search per frame. Only the two bracketing
        anchors and one flow pair are held at a time.
        """
        output = context.output
        anchors = context.anchors
        params = context.controls

        problems = _validate_controls(dict(params), output)
        blocking = [i for i in problems if i.severity is IssueSeverity.ERROR]
        if blocking:
            # The service validates before reaching here; this covers an adapter
            # driven directly, using the same check so the two cannot disagree.
            raise AdapterError(blocking[0].message)

        block_size = int(
            _coerce_numeric(params.get("block_size", DEFAULT_BLOCK_SIZE), "block_size")
        )
        search_radius = int(
            _coerce_numeric(params.get("search_radius", DEFAULT_SEARCH_RADIUS), "search_radius")
        )
        accept_margin = _coerce_numeric(
            params.get("accept_margin", DEFAULT_ACCEPT_MARGIN), "accept_margin"
        )

        indices = anchors.indices
        cancel = context.cancel_requested
        cached_pair: tuple[int, int] | None = None
        forward: NDArray[np.float32] | None = None
        backward: NDArray[np.float32] | None = None

        for frame_index in range(output.animation_frame_count):
            if isinstance(cancel, threading.Event) and cancel.is_set():
                return
            left_pos = max(i for i, idx in enumerate(indices) if idx <= frame_index)
            if indices[left_pos] == frame_index:
                # An approved anchor is delivered exactly, never re-sampled.
                yield np.ascontiguousarray(context.anchor_frames[frame_index])
                continue
            right_pos = min(i for i, idx in enumerate(indices) if idx > frame_index)
            left_idx, right_idx = indices[left_pos], indices[right_pos]
            left = context.anchor_frames[left_idx]
            right = context.anchor_frames[right_idx]

            if cached_pair != (left_idx, right_idx):
                forward = estimate_block_flow(
                    left,
                    right,
                    block_size=block_size,
                    search_radius=search_radius,
                    accept_margin=accept_margin,
                )
                backward = estimate_block_flow(
                    right,
                    left,
                    block_size=block_size,
                    search_radius=search_radius,
                    accept_margin=accept_margin,
                )
                cached_pair = (left_idx, right_idx)
                context.notes.append(
                    f"classical flow estimated for anchors {left_idx}->{right_idx}: "
                    f"mean |displacement| {float(np.abs(forward).mean()):.2f}px"
                )

            assert forward is not None and backward is not None  # set with cached_pair
            timestep = (frame_index - left_idx) / (right_idx - left_idx)
            yield interpolate_motion_compensated(
                left, right, timestep, forward, backward, block_size=block_size
            )
