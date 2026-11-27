"""Frame-indexed, reusable performance tracks for the cinematic built-in cast."""

from __future__ import annotations

from functools import cache
from importlib.resources import files
from itertools import pairwise
from typing import Annotated, Literal

from pydantic import Field, FiniteFloat, TypeAdapter, model_validator

from animalite.contracts.base import Contract

Vec3 = tuple[FiniteFloat, FiniteFloat, FiniteFloat]
Hand = Literal["left", "right"]
Frame = Annotated[int, Field(ge=1, le=144)]
Color = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]


class CharacterDesign(Contract):
    skin: Color = "#94B979"
    shirt: Color = "#E69345"
    costume: Literal["cap", "forelock"] = "forelock"
    size: float = Field(default=1, ge=0.5, le=2)
    limb_scale: float = Field(default=1, ge=0.8, le=1.25)


class Beat(Contract):
    frame: Frame
    end: Frame
    ease: Literal["smooth", "linear"] = "smooth"

    @model_validator(mode="after")
    def forward(self) -> Beat:
        if self.end < self.frame:
            raise ValueError("a beat must end on or after its start frame")
        return self


class Shift(Beat):
    offset: Vec3 = (0, 0, 0)
    lean: float = Field(default=0, ge=-65, le=65)
    turn: float = Field(default=0, ge=-180, le=180)


class Step(Beat):
    offset: Vec3


class Target(Contract):
    actor: str | None = None
    prop: str | None = None
    grip: str = "center"
    point: Vec3 | None = None
    local: Vec3 | None = None
    offset: Vec3 = (0, 0, 0)

    @model_validator(mode="after")
    def destination(self) -> Target:
        if sum(x is not None for x in (self.actor, self.prop, self.point, self.local)) != 1:
            raise ValueError("target exactly one actor, prop, local point or world point")
        if self.prop is None and self.grip != "center":
            raise ValueError("named grips belong to props")
        return self


class Aim(Beat):
    target: Target


class Reach(Aim):
    rotation: Vec3 | None = None
    arc_height: FiniteFloat = Field(default=0, ge=0)


class Motion(Contract):
    body: list[Shift] = Field(default_factory=list)
    left_foot: list[Step] = Field(default_factory=list)
    right_foot: list[Step] = Field(default_factory=list)
    left_hand: list[Reach] = Field(default_factory=list)
    right_hand: list[Reach] = Field(default_factory=list)
    eyes: list[Aim] = Field(default_factory=list)
    head: list[Aim] = Field(default_factory=list)

    def tracks(self) -> dict[str, list[Beat]]:
        return {name: getattr(self, name) for name in type(self).model_fields}

    @model_validator(mode="after")
    def sequential(self) -> Motion:
        for name, beats in self.tracks().items():
            if any(b.frame <= a.end for a, b in pairwise(beats)):
                raise ValueError(f"overlapping or unordered beats on {name}")
        return self


class Prop(Contract):
    kind: Literal["biscuit", "tin", "ball", "box"]
    position: Vec3
    rotation: Vec3 = (0, 0, 0)
    size: float = Field(default=1, ge=0.1, le=5)
    color: Color = "#DE994B"
    grips: dict[str, Vec3] = Field(default_factory=dict)

    @model_validator(mode="after")
    def center_reserved(self) -> Prop:
        if "center" in self.grips:
            raise ValueError("center is the built-in grip at the prop origin")
        return self


class Contact(Contract):
    frame: Frame
    action: Literal["grasp", "release", "handoff"]
    prop: str
    actor: str
    hand: Hand
    grip: str = "center"


def check_grip(props: dict[str, Prop], name: str, grip: str) -> None:
    if name not in props or (grip != "center" and grip not in props[name].grips):
        raise ValueError(f"unknown prop or grip {name}.{grip}")


def validate_contacts(
    contacts: list[Contact], props: dict[str, Prop], actors: set[str], frames: int
) -> None:
    owners: dict[str, tuple[str, Hand]] = {}
    last = 0
    seen: set[tuple[int, str]] = set()
    for event in contacts:
        check_grip(props, event.prop, event.grip)
        if event.actor not in actors:
            raise ValueError(f"unknown contact actor {event.actor}")
        if event.frame > frames or event.frame < last or (event.frame, event.prop) in seen:
            raise ValueError(
                "contact frames must be in order and distinct per prop within the shot"
            )
        last = event.frame
        seen.add((last, event.prop))
        hand = (event.actor, event.hand)
        previous = owners.get(event.prop)
        if event.action == "release":
            if previous != hand:
                raise ValueError(f"only the current owner can release {event.prop}")
            del owners[event.prop]
            continue
        if (event.action == "grasp") != (previous is None) or hand in owners.values():
            raise ValueError(f"invalid {event.action} or occupied hand for {event.prop}")
        owners[event.prop] = hand


@cache
def builtin_moves() -> dict[str, Motion]:
    library = files("animalite").joinpath("performance_moves.json").read_bytes()
    return TypeAdapter(dict[str, Motion]).validate_json(library)
