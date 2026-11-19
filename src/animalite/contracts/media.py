"""Declared media contract: cadence, output geometry, codec and frame accounting.

Section 12.0 core output row is the reference case: 640x360, 72 animation frames
at 12 animation fps, two-frame holds giving 144 delivery frames at 24 fps and
exactly 6.000 seconds.
"""

from __future__ import annotations

from fractions import Fraction

from pydantic import Field, model_validator

from animalite.contracts.base import Contract
from animalite.contracts.enums import CadenceConversion

__all__ = [
    "PREVIEW_OUTPUT",
    "P_L_FINAL_OUTPUT",
    "CadencePolicy",
    "FrameAccounting",
    "OutputSpec",
]


class CadencePolicy(Contract):
    """CR-004 / A-07 cadence lock.

    Frame duplication is the project default conversion from 12 unique
    animation fps to a 24 fps delivery stream. Interpolated uplift is a
    separately approved and budgeted exception (D-09), so it is representable
    here but rejected by :meth:`hold_factor` consumers until approved.
    """

    animation_fps: int = Field(default=12, ge=1, le=120)
    delivery_fps: int = Field(default=24, ge=1, le=240)
    conversion: CadenceConversion = CadenceConversion.DUPLICATE

    @model_validator(mode="after")
    def _check_conversion(self) -> CadencePolicy:
        if self.delivery_fps < self.animation_fps:
            raise ValueError(
                f"delivery_fps ({self.delivery_fps}) must be >= "
                f"animation_fps ({self.animation_fps})"
            )
        duplicate = self.conversion is CadenceConversion.DUPLICATE
        if duplicate and self.delivery_fps % self.animation_fps != 0:
            raise ValueError(
                "cadence_conversion 'duplicate' requires delivery_fps to be an "
                f"integer multiple of animation_fps; got {self.delivery_fps}/"
                f"{self.animation_fps}"
            )
        return self

    @property
    def hold_factor(self) -> int:
        """Delivery frames emitted per animation frame.

        Only defined for the duplicate conversion; interpolated uplift produces
        new temporal information and is not a hold.
        """
        if self.conversion is not CadenceConversion.DUPLICATE:
            raise ValueError(
                "hold_factor is only defined for cadence_conversion 'duplicate'; "
                f"this policy uses '{self.conversion.value}'"
            )
        return self.delivery_fps // self.animation_fps


class OutputSpec(Contract):
    """Every output-affecting media setting, fixed before execution.

    Handoff section 2 (Media): "Fix dimensions, frame indexing, cadence, pixel
    format and codec profile; include them in the run record."
    """

    width: int = Field(ge=16, le=7680)
    height: int = Field(ge=16, le=4320)
    animation_frame_count: int = Field(ge=2, le=100_000)
    cadence: CadencePolicy = CadencePolicy()
    container: str = "mp4"
    codec: str = "libx264"
    codec_profile: str = "high"
    codec_level: str = "3.1"
    pixel_format: str = "yuv420p"
    rate_control: str = "crf"
    crf: int = Field(default=18, ge=0, le=51)
    preset: str = "medium"
    color_primaries: str = "bt709"
    color_transfer: str = "bt709"
    color_matrix: str = "bt709"
    color_range: str = "tv"

    @model_validator(mode="after")
    def _check_dimensions(self) -> OutputSpec:
        # yuv420p subsamples chroma 2x2; odd dimensions are silently padded by
        # some encoders, which would break the declared geometry.
        if self.pixel_format.startswith("yuv420") and (self.width % 2 or self.height % 2):
            raise ValueError(
                f"pixel_format {self.pixel_format} requires even dimensions; "
                f"got {self.width}x{self.height}"
            )
        return self

    @property
    def delivery_frame_count(self) -> int:
        return self.animation_frame_count * self.cadence.hold_factor

    @property
    def duration_seconds(self) -> Fraction:
        """Exact duration as a rational number.

        Returned as a :class:`~fractions.Fraction` so 144/24 compares equal to
        exactly 6 without float tolerance games.
        """
        return Fraction(self.delivery_frame_count, self.cadence.delivery_fps)

    @property
    def last_animation_index(self) -> int:
        return self.animation_frame_count - 1

    @property
    def aspect_ratio(self) -> Fraction:
        return Fraction(self.width, self.height)


class FrameAccounting(Contract):
    """Section 12.0: report synthesized, source and duplicate counts separately.

    ``duplicated_frame_count`` counts delivery frames that repeat an animation
    frame already counted once; it is never reported as new temporal
    information.
    """

    animation_frame_count: int = Field(ge=0)
    delivery_frame_count: int = Field(ge=0)
    source_frame_count: int = Field(ge=0)
    synthesized_frame_count: int = Field(ge=0)
    duplicated_frame_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _check_totals(self) -> FrameAccounting:
        counted = self.source_frame_count + self.synthesized_frame_count
        if counted != self.animation_frame_count:
            raise ValueError(
                "source_frame_count + synthesized_frame_count must equal "
                f"animation_frame_count; got {self.source_frame_count} + "
                f"{self.synthesized_frame_count} != {self.animation_frame_count}"
            )
        expected_dupes = self.delivery_frame_count - self.animation_frame_count
        if self.duplicated_frame_count != expected_dupes:
            raise ValueError(
                "duplicated_frame_count must equal delivery_frame_count - "
                f"animation_frame_count; got {self.duplicated_frame_count} != "
                f"{expected_dupes}"
            )
        return self


#: Section 12.0 "Core output" row.
P_L_FINAL_OUTPUT = OutputSpec(width=640, height=360, animation_frame_count=72)

#: Section 12.0 "Warm preview" row: playable 3-second 320x180 preview at 12
#: animation fps. Section 12.0 does not state the preview delivery frame rate;
#: DEC-0005 keeps the project cadence policy (12 -> 24 by duplication).
PREVIEW_OUTPUT = OutputSpec(width=320, height=180, animation_frame_count=36, crf=23)
