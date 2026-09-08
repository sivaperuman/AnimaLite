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

from collections.abc import Iterator
from typing import Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray

from animalite.contracts.assets import AnchorSet
from animalite.contracts.media import OutputSpec
from animalite.contracts.profile import Capabilities, EngineProfile
from animalite.contracts.validation import ValidationIssue

__all__ = ["AdapterContext", "MotionAdapter"]


class AdapterContext:
    """Everything an adapter needs that is not part of the request contract."""

    def __init__(
        self,
        *,
        anchor_frames: dict[int, NDArray[np.uint8]],
        output: OutputSpec,
        anchors: AnchorSet,
        profile: EngineProfile,
        cancel_requested: object | None = None,
    ) -> None:
        self.anchor_frames = anchor_frames
        self.output = output
        self.anchors = anchors
        self.profile = profile
        self.cancel_requested = cancel_requested


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
