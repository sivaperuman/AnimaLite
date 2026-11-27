"""Approved input anchors and content-addressed asset references (NFR-003)."""

from __future__ import annotations

import re
from fractions import Fraction
from typing import Annotated

from pydantic import Field, field_validator, model_validator

from animalite.contracts.base import Contract, Document
from animalite.contracts.media import OutputSpec

__all__ = ["SHA256_PATTERN", "AnchorSet", "AssetRef", "InputAnchor"]

SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")

#: Section 12.0 input row: 2-4 approved frames for a 6-second clip.
MIN_ANCHORS = 2
MAX_ANCHORS = 4


class AssetRef(Contract):
    """An immutable, content-addressed reference to a file on disk."""

    path: str
    content_hash: str
    size_bytes: int | None = Field(default=None, ge=0)
    media_type: str | None = None

    @field_validator("content_hash")
    @classmethod
    def _check_hash(cls, value: str) -> str:
        if not SHA256_PATTERN.match(value):
            raise ValueError(f"content_hash must match 'sha256:<64 hex>'; got {value!r}")
        return value


class VideoConditioning(Contract):
    """Optional frame-indexed appearance and motion controls for neural video."""

    reference_image: AssetRef | None = None
    control_video: AssetRef | None = None
    mask_image: AssetRef | None = None
    mask_video: AssetRef | None = None
    anchor_strengths: dict[int, Annotated[float, Field(ge=0, le=1)]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def one_mask(self) -> VideoConditioning:
        if self.mask_image and self.mask_video:
            raise ValueError("choose a static mask or a moving mask")
        return self

    def assets(self) -> dict[str, AssetRef]:
        return {
            name: asset
            for name, asset in (
                ("reference_image", self.reference_image),
                ("control_video", self.control_video),
                ("mask_image", self.mask_image),
                ("mask_video", self.mask_video),
            )
            if asset is not None
        }


class InputAnchor(Contract):
    """One approved, time-indexed source frame.

    ``animation_index`` is an index into the animation stream (0-based), not the
    delivery stream. Section 12.0 pins the first and last anchors to animation
    indices 0 and 71 for the 72-frame core output.
    """

    anchor_id: str = Field(min_length=1)
    animation_index: int = Field(ge=0)
    asset: AssetRef
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    approved: bool = True

    @property
    def aspect_ratio(self) -> Fraction:
        return Fraction(self.width, self.height)


class AnchorSet(Document):
    """A validated ordered set of 2-4 approved anchors for one shot.

    Structural rules enforced here (count, strict ordering, endpoint indices,
    uniform geometry) are the ones that are *always* wrong when violated. Rules
    that depend on a chosen profile or output live in
    :mod:`animalite.core.validation` so they can be reported as actionable
    validation issues rather than construction errors.
    """

    anchors: list[InputAnchor] = Field(min_length=MIN_ANCHORS, max_length=MAX_ANCHORS)

    @model_validator(mode="after")
    def _check_ordering(self) -> AnchorSet:
        indices = [a.animation_index for a in self.anchors]
        if indices != sorted(indices):
            raise ValueError(f"anchor animation_index values must ascend; got {indices}")
        if len(set(indices)) != len(indices):
            raise ValueError(f"anchor animation_index values must be unique; got {indices}")
        ids = [a.anchor_id for a in self.anchors]
        if len(set(ids)) != len(ids):
            raise ValueError(f"anchor_id values must be unique; got {ids}")
        first = self.anchors[0]
        if any((a.width, a.height) != (first.width, first.height) for a in self.anchors):
            raise ValueError(
                "all anchors must share one pixel geometry; got "
                + ", ".join(f"{a.anchor_id}={a.width}x{a.height}" for a in self.anchors)
            )
        return self

    @property
    def count(self) -> int:
        return len(self.anchors)

    @property
    def indices(self) -> list[int]:
        return [a.animation_index for a in self.anchors]

    def endpoints_match(self, output: OutputSpec) -> bool:
        """True when the first/last anchors sit on animation indices 0 and N-1."""
        return (
            self.anchors[0].animation_index == 0
            and self.anchors[-1].animation_index == output.last_animation_index
        )
