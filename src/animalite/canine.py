"""Reusable dog designs and an independently directable gallop shot."""

from __future__ import annotations

from dataclasses import dataclass
from math import exp
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from animalite.contracts.base import Contract
from animalite.gallop import DogRig, Leg, gallop_legs, stride_length, torso_bounce

Look = Literal["ink", "painted-anime"]
View = Literal["profile", "three-quarter"]
Color = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]


class HeadDrawing(Contract):
    """Transparent image in a square local box. The anchor is its normalized neck pivot."""

    image: Path
    anchor_x: float = Field(default=0.34, ge=0, le=1)
    anchor_y: float = Field(default=0.80, ge=0, le=1)
    size_in_trunks: float = Field(default=0.68, gt=0.1, le=2)


class DogDesign(Contract):
    rig: DogRig = DogRig()
    trunk: float = Field(default=100, ge=40, le=150)
    silhouette: Literal["floppy", "sighthound"] = "floppy"
    coat: Color = "#fff5df"
    shadow: Color = "#c7b8a4"
    marking: Color = "#d7af82"
    collar: Color = "#a13d35"
    head_drawings: dict[Look, dict[View, HeadDrawing]] = Field(default_factory=dict)


class HeadCue(Contract):
    frame: int = Field(ge=0)
    view: View


class GallopShot(Contract):
    dog: str = Field(min_length=1)
    look: Look = "ink"
    direction: Literal["right", "left"] = "right"
    speed: float = Field(default=2.75, ge=0.8, le=5, description="Trunk lengths per second")
    extension: float = Field(default=1.0, ge=0.75, le=1.30, description="Stride-length multiplier")
    camera_follow: float = Field(default=0.78, ge=0, le=1, description="One locks the dog in frame")
    backdrop: Path | None = None
    head_cues: list[HeadCue] = Field(default_factory=list)

    @model_validator(mode="after")
    def ordered_cues(self) -> GallopShot:
        frames = [cue.frame for cue in self.head_cues]
        if frames != sorted(set(frames)):
            raise ValueError("head cues must increase strictly")
        return self


@dataclass(frozen=True)
class GallopFrame:
    body: complex
    legs: tuple[Leg, ...]
    length: float
    camera: float
    facing: int
    screen_origin: float
    floor_y: float
    phase: float
    head_view: View

    def screen(self, point: complex) -> complex:
        return complex(self.screen_origin + self.facing * (point.real - self.camera), point.imag)


def running_frame(shot: GallopShot, design: DogDesign, index: int, width: float) -> GallopFrame:
    length = design.trunk * min(1.0, width / 350)
    distance = index / 24 * shot.speed * length
    stride = stride_length(design.rig, length, shot.extension)
    floor_y = 282.0
    mean_height = (design.rig.shoulder_height + design.rig.hip_height) / 2
    body = complex(
        distance, floor_y - mean_height * length + torso_bounce(distance, stride, length)
    )
    legs = gallop_legs(design.rig, body, length, lambda _x: floor_y, extension=shot.extension)
    # The camera picks up the subject on entry. The bounded lead room also works in portrait.
    lag = (1 - shot.camera_follow) * width * 0.22 * (1 - exp(-distance / (width * 0.21)))
    direction = 1 if shot.direction == "right" else -1
    view: View = "profile"
    for cue in shot.head_cues:
        if cue.frame > index:
            break
        view = cue.view
    return GallopFrame(
        body,
        legs,
        length,
        distance - lag,
        direction,
        width * (0.43 if direction == 1 else 0.57),
        floor_y,
        distance / stride,
        view,
    )
