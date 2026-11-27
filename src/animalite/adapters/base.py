"""The motion adapter boundary.

Handoff rule 1: "Keep inference outside the domain layer. Core types must not
import model-specific packages." Nothing in :mod:`animalite.contracts` or
:mod:`animalite.core` imports an adapter implementation; adapters are resolved
through the registry by ``adapter_key``.

An adapter yields *animation* frames. Cadence expansion, encoding, output
validation and publishing are the pipeline's job, not the adapter's, so every
adapter -- fixture, classical or learned -- goes through exactly one media path.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray

from animalite.contracts.admission import AdmissionPurpose
from animalite.contracts.assets import AnchorSet
from animalite.contracts.media import OutputSpec
from animalite.contracts.profile import Capabilities, EngineProfile
from animalite.contracts.results import DeviceEvidence
from animalite.contracts.validation import ValidationIssue
from animalite.errors import JobCancelled, JobTimeoutError
from animalite.media.ffmpeg import FFmpegTools

__all__ = ["AdapterContext", "MotionAdapter"]


class AdapterContext:
    """Everything an adapter needs that is not part of the request contract.

    ``device_evidence`` and ``notes`` are *outputs*: an adapter that drives a
    native runtime sets them during :meth:`MotionAdapter.synthesize`, and the
    execution service copies them into the attempt record. They live on the
    per-job context rather than on the adapter because the registry holds one
    adapter instance shared across jobs.
    """

    def __init__(
        self,
        *,
        anchor_frames: dict[int, NDArray[np.uint8]],
        output: OutputSpec,
        anchors: AnchorSet,
        profile: EngineProfile,
        scratch_dir: Path,
        tools: FFmpegTools,
        controls: Mapping[str, float | int | str | bool] | None = None,
        cancel_requested: object | None = None,
        deadline: float | None = None,
        cancel: Callable[[], bool] | None = None,
        purpose: AdmissionPurpose = AdmissionPurpose.RESEARCH,
    ) -> None:
        self.anchor_frames = anchor_frames
        self.output = output
        self.anchors = anchors
        self.profile = profile
        #: Attempt-owned scratch directory. An adapter may write here freely;
        #: the contents are retained as diagnostics when the attempt fails and
        #: are never published as output.
        self.scratch_dir = scratch_dir
        #: **Effective** controls: profile defaults with the request's validated
        #: overrides applied. Adapters must read these rather than
        #: ``profile.parameters`` -- otherwise a request control changes the
        #: settings digest without changing a pixel, which is precisely what the
        #: digest exists to detect.
        self.controls: dict[str, float | int | str | bool] = dict(controls or {})
        #: The media tools the *service* selected and verified. An adapter must
        #: use these rather than rediscovering its own pair: otherwise a
        #: process-cold envelope can preserve the service's media identity while
        #: the learned path quietly runs a different FFmpeg.
        self.tools = tools
        self.cancel_requested = cancel_requested
        #: Absolute monotonic job deadline shared with the rest of the pipeline.
        #: Every native operation an adapter launches is bounded by what is left
        #: of *this*, never by a private per-call timeout.
        self.deadline = deadline
        #: Cancellation predicate, checked inside long operations rather than
        #: only between them. The adapter generator is pulled synchronously by
        #: the encoder, so while `next(frames)` is stalled nothing else in the
        #: pipeline can enforce either bound.
        self.cancel = cancel
        #: What this run is for. An adapter that executes third-party model
        #: artifacts checks admission against it before launching anything; a
        #: record clearing research does not clear benchmark or delivered output.
        self.purpose = purpose
        #: Set by adapters that can evidence the device their runtime used.
        self.device_evidence: DeviceEvidence | None = None
        #: Free-form observations to attach to the attempt log.
        self.notes: list[str] = []

    def remaining_seconds(self) -> float:
        """Time left on the job deadline; raises when it has already expired.

        Called before launching each native operation, so an expired deadline
        starts nothing rather than granting one more full-length call.
        """
        if self.deadline is None:
            raise JobTimeoutError(
                "no job deadline was supplied to the adapter; a native operation "
                "must not run unbounded"
            )
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise JobTimeoutError(
                "the job deadline expired before this operation could start; nothing was launched"
            )
        return left

    def raise_if_cancelled(self, during: str) -> None:
        """Stop promptly when cancellation was requested."""
        if self.cancel is not None and self.cancel():
            raise JobCancelled(f"cancellation requested while {during}")

    def checkpoint(self, during: str) -> None:
        """Cooperative stopping point inside a long pure-Python computation.

        Cheap enough to call from inside a loop, so a search that takes seconds
        is interruptible part-way rather than only between frames. Unlike
        :meth:`remaining_seconds` it tolerates an absent deadline: a computation
        with no native child to leak is bounded by the pipeline around it, and a
        context built without a deadline should still honour cancellation.
        """
        self.raise_if_cancelled(during)
        if self.deadline is not None and self.deadline - time.monotonic() <= 0:
            raise JobTimeoutError(f"the job deadline expired while {during}")

    def effective_controls(self) -> dict[str, float | int | str | bool]:
        """Profile defaults with this context's overrides applied.

        The same resolution validation performed, so an adapter cannot execute
        a different configuration from the one that was checked. Idempotent: the
        service already passes the resolved mapping, and a context built
        directly (a test, a tool) gets the defaults filled in here.
        """
        return self.profile.effective_controls(self.controls)


@runtime_checkable
class MotionAdapter(Protocol):
    """Adapter contract used by the execution service."""

    key: str

    def capabilities(self, profile: EngineProfile) -> Capabilities:
        """Report the controls, tiers, resolutions and frame ranges actually supported."""

    def validate(
        self,
        profile: EngineProfile,
        anchors: AnchorSet,
        output: OutputSpec,
        controls: dict[str, float | int | str | bool],
    ) -> list[ValidationIssue]:
        """Return adapter-specific validation issues. An unsupported control is an issue."""

    def synthesize(self, context: AdapterContext) -> Iterator[NDArray[np.uint8]]:
        """Yield exactly ``output.animation_frame_count`` RGB24 animation frames."""
