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

from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray

from animalite.contracts.assets import AnchorSet
from animalite.contracts.media import OutputSpec
from animalite.contracts.profile import Capabilities, EngineProfile
from animalite.contracts.results import DeviceEvidence
from animalite.contracts.validation import ValidationIssue

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
        controls: Mapping[str, float | int | str | bool] | None = None,
        cancel_requested: object | None = None,
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
        self.cancel_requested = cancel_requested
        #: Set by adapters that can evidence the device their runtime used.
        self.device_evidence: DeviceEvidence | None = None
        #: Free-form observations to attach to the attempt log.
        self.notes: list[str] = []


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
