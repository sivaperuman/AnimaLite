"""Reusable dog designs and an independently directable gallop shot."""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, exp, pi
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from animalite.choreography import Hand
from animalite.contracts.base import Contract
from animalite.dog_action import (
    RunAction,
    articulated_legs,
    sample_action,
)
from animalite.gallop import DogRig, Leg, gallop_legs, stride_length, torso_bounce

Look = Literal["ink", "painted-anime"]
View = Literal["profile", "three-quarter"]
BodyKey = Literal["compressed", "extended", "quarter", "front"]
Color = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]


class HeadDrawing(Contract):
    """Transparent image in a square local box. The anchor is its normalized neck pivot."""

    image: Path
    anchor_x: float = Field(default=0.34, ge=0, le=1)
    anchor_y: float = Field(default=0.80, ge=0, le=1)
    size_in_trunks: float = Field(default=0.68, gt=0.1, le=2)


class BodyDrawing(Contract):
    """Square transparent cel containing the trunk, head and tail, registered at the tag."""

    image: Path
    ink_image: Path | None = None
    anchor_x: float = Field(ge=0, le=1)
    anchor_y: float = Field(ge=0, le=1)
    size_in_trunks: float = Field(gt=0.1, le=4)


class DogDesign(Contract):
    rig: DogRig = DogRig()
    trunk: float = Field(default=100, ge=40, le=150)
    silhouette: Literal["floppy", "sighthound"] = "floppy"
    coat: Color = "#fff5df"
    shadow: Color = "#c7b8a4"
    marking: Color = "#d7af82"
    collar: Color = "#a13d35"
    body_drawings: dict[BodyKey, BodyDrawing] = Field(default_factory=dict)
    head_drawings: dict[Look, dict[View, HeadDrawing]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def complete_body_views(self) -> DogDesign:
        if self.body_drawings and set(self.body_drawings) != {
            "extended",
            "compressed",
            "quarter",
            "front",
        }:
            raise ValueError(
                "body_drawings requires extended, compressed, quarter and front artwork"
            )
        return self


class HeadCue(Contract):
    frame: int = Field(ge=0)
    view: View


class LeadHandler(Contract):
    hand: Hand = "right"
    actor: str = Field(min_length=1, description="Name of a character in the storyboard cast")
    leash_length: float = Field(default=1.22, ge=0.65, le=1.8, description="Trunk lengths")
    surprise_hold_frames: int = Field(default=14, ge=0, le=120)


class GallopShot(Contract):
    dog: str = Field(min_length=1)
    look: Look = "ink"
    direction: Literal["right", "left"] = "right"
    speed: float = Field(default=2.75, ge=0.8, le=5, description="Trunk lengths per second")
    extension: float = Field(default=1.0, ge=0.75, le=1.30, description="Stride-length multiplier")
    camera_follow: float = Field(default=0.78, ge=0, le=1, description="One locks the dog in frame")
    performance: RunAction | None = None
    handler: LeadHandler | None = None
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

    turn: float = 0
    stretch: float = 1
    pitch: float = 0
    stage: str = "gallop"

    @property
    def yaw(self) -> float:
        return cos(pi * self.turn)

    def body_key(self) -> BodyKey:
        if 0.36 <= self.turn <= 0.64:
            return "front"
        if self.head_view == "three-quarter" or 0.12 < self.turn < 0.88:
            return "quarter"
        if self.stage in {"stand", "settle"}:
            return "compressed"
        if self.stretch != 1:
            return "extended" if self.stretch > 1 else "compressed"
        return "extended" if cos(2 * pi * self.phase) >= 0 else "compressed"

    def collar(self, dog: DogDesign) -> complex:
        neck = complex(38, -33) if dog.silhouette == "sighthound" else complex(36, -25)
        return self.torso_point(neck + 5 + 14j)

    def torso_point(self, offset: complex) -> complex:
        return (
            self.body
            + complex(offset.real * self.stretch * self.yaw, offset.imag + offset.real * self.pitch)
            * self.length
            / 100
        )

    def screen(self, point: complex) -> complex:
        return complex(self.screen_origin + self.facing * (point.real - self.camera), point.imag)


def running_frame(shot: GallopShot, design: DogDesign, index: int, width: float) -> GallopFrame:
    length = design.trunk * min(1.0, width / 350)
    if shot.handler:
        length = min(length, width * 0.23)
    distance = index / 24 * shot.speed * length
    action = sample_action(shot.performance, index, shot.speed) if shot.performance else None
    activity = action.activity if action else 1.0
    if action:
        distance = action.distance * length
    stride = stride_length(design.rig, length, shot.extension)
    floor_y = 282.0
    mean_height = (design.rig.shoulder_height + design.rig.hip_height) / 2
    body = complex(
        distance, floor_y - mean_height * length + activity * torso_bounce(distance, stride, length)
    )
    legs = gallop_legs(
        design.rig,
        body,
        length,
        lambda _x: floor_y,
        extension=shot.extension,
        active=activity,
        rest_center=distance,
    )
    stretch = 1.0
    pitch = action.pitch + 0.055 * activity * cos(2 * pi * distance / stride) if action else 0
    if action and shot.performance:
        total = (
            sample_action(shot.performance, shot.performance.stop_frame, shot.speed).distance
            * length
        )
        legs, stretch = articulated_legs(
            legs,
            body,
            length,
            activity,
            pitch,
            action.turn,
            total,
            stride,
            floor_y,
            (index - shot.performance.launch_frame) / shot.performance.acceleration_frames,
            1 if action.stage in {"launch", "gallop"} else activity,
        )
    # The camera picks up the subject on entry. The bounded lead room also works in portrait.
    lag = (1 - shot.camera_follow) * width * 0.22 * (1 - exp(-distance / (width * 0.21)))
    direction = 1 if shot.direction == "right" else -1
    view: View = "profile"
    for cue in shot.head_cues:
        if cue.frame > index:
            break
        view = cue.view
    origin = 0.62 if shot.handler else 0.43
    return GallopFrame(
        body,
        legs,
        length,
        distance - lag,
        direction,
        width * (origin if direction == 1 else 1 - origin),
        floor_y,
        distance / stride,
        "three-quarter" if action and 0.18 < action.turn < 0.82 else view,
        action.turn if action else 0,
        stretch,
        pitch,
        action.stage if action else "gallop",
    )
