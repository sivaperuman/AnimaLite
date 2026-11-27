"""Directed dog-walk performance in stage pixels (360 by 640, y down, 24 fps)."""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, floor, pi, sin, sqrt
from typing import Literal

from pydantic import Field

from animalite.contracts.base import Contract
from animalite.dog_walk_fall import FallBlocking, blocking
from animalite.gallop import DogRig, Leg, gallop_legs

FPS = 24
FRAMES = 240
GROUND = 475.0
LEASH = 102.0


class DogWalk(Contract):
    """A slice of a continuous ten-second performance; frame zero is its origin."""

    direction: Literal["right", "left"] = "right"
    launch_frame: int = Field(default=44, ge=30, le=60)
    start_frame: int = Field(default=0, ge=0, lt=FRAMES)
    performance: Literal["walk-and-sit", "fall-and-recover"] = "walk-and-sit"
    contact_overlay: bool = False
    handler: str = Field(default="Milo", min_length=1)


def ease(t: float, a: float, b: float) -> float:
    u = min(1.0, max(0.0, (t - a) / (b - a)))
    return u * u * (3 - 2 * u)


@dataclass(frozen=True)
class Paw:
    tip: complex
    planted: bool


def gait(
    distance: float,
    offset: float,
    phase_offset: float,
    stride: float,
    ground: float,
    support: float = 0.51,
) -> Paw:
    """The world-space contact point is constant throughout each support phase."""
    cycle = distance / stride + phase_offset
    step = floor(cycle)
    phase = cycle - step
    contact = (step - phase_offset + 0.255) * stride + offset
    if phase <= support:
        return Paw(complex(contact, ground), True)
    swing = (phase - support) / (1 - support)
    x = contact + stride * ease(swing, 0, 1)
    return Paw(complex(x, ground - 13 * sin(pi * swing) ** 1.4), False)


@dataclass(frozen=True)
class Leash:
    hand: complex
    control: complex
    collar: complex

    def point(self, u: float) -> complex:
        return (1 - u) ** 2 * self.hand + 2 * (1 - u) * u * self.control + u * u * self.collar


def leash(hand: complex, collar: complex) -> Leash:
    """Find the downward bow with the specified arc length; a taut lead is straight."""
    chord = collar - hand
    length = abs(chord)
    mid = (hand + collar) / 2
    if length > LEASH + 1e-7:
        raise ValueError("leash endpoints exceed its length")
    if length == 0:
        return Leash(hand, mid + LEASH * 1j, collar)
    if length >= LEASH - 1e-7:
        return Leash(hand, mid, collar)
    # Quadratic control on the chord's perpendicular bisector. Simpson quadrature
    # integrates the speed along the symmetric half curve.
    lo, hi = 0.0, LEASH
    for _ in range(18):
        bow = (lo + hi) / 2
        samples = [abs(complex(length, 2 * bow * i / 8)) for i in range(9)]
        arc = (samples[0] + samples[-1] + 4 * sum(samples[1::2]) + 2 * sum(samples[2:-1:2])) / 24
        if arc < LEASH:
            lo = bow
        else:
            hi = bow
    return Leash(hand, mid + 1j * chord / length * ((lo + hi) / 2), collar)


@dataclass(frozen=True)
class Pose:
    t: float
    dog: complex
    paws: tuple[Paw, ...]
    lead: Leash
    hip: complex
    shoulder: complex
    face: complex
    feet: tuple[complex, ...]
    free_hand: complex
    lift: float
    seated: float
    look_back: float
    camera_x: float
    legs: tuple[Leg, ...]
    fall: FallBlocking | None = None


def picture_to_stage(point: complex, camera: float) -> complex:
    return complex(
        camera + (point.real * 2.5 - 180) / 1.42, GROUND + (point.imag * 2.5 - 475) / 1.42
    )


def fall_pose(t: float) -> Pose:
    f = blocking(t)
    body = f.body
    camera = f.camera * 2.5 / 1.42

    def world(point: complex) -> complex:
        return picture_to_stage(point, camera)

    dog = world(body.dog)
    rest_x = (
        picture_to_stage(103 + 171j, 426.5 * 2.5 / 1.42).real
        if t > 100
        else picture_to_stage(90 + 194j, 0).real
    )

    def pavement(x: float) -> float:
        return world(complex(0, 214 - 23 * ease(x * 1.42 / 2.5, 21, 459))).imag

    legs = gallop_legs(DogRig(), dog, 56, pavement, active=f.sprint, rest_center=rest_x)
    # The vector terrier has its own collar attachment relative to the torso.
    collar = dog + complex(17, -12)
    collar_offset = collar - world(f.collar)
    return Pose(
        t,
        dog,
        tuple(Paw(leg.tip, leg.planted) for leg in legs),
        Leash(
            world(f.lead_end) + collar_offset * f.release,
            world(f.lead_control) + collar_offset * ((1 + f.release) / 2),
            collar,
        ),
        world(body.hip),
        world(body.neck),
        world(body.face),
        (world(body.far_foot), world(body.near_foot)),
        world(body.free),
        f.lift,
        f.seated,
        f.turn,
        camera,
        legs,
        f,
    )


def pose(frame: int, action: DogWalk) -> Pose:
    if not 0 <= frame < FRAMES:
        raise ValueError("dog-walk frame outside performance")
    # Retime only the launch. The landing and dialogue still share a stable clock.
    if frame <= action.launch_frame:
        t = frame * 44.0 / action.launch_frame
    elif frame < 122:
        t = 44 + (frame - action.launch_frame) * 78 / (122 - action.launch_frame)
    else:
        t = float(frame)

    if action.performance == "fall-and-recover":
        return fall_pose(t)

    walk = 34 * ease(t, 0, 31)
    distance = walk + 285 * ease(t, 44, 126)
    phase = distance / 54 * 2 * pi
    activity = 1 - ease(t, 121, 139)
    crouch = ease(t, 32, 41) - ease(t, 41, 51)
    sprint = ease(t, 47, 65) - ease(t, 111, 126)
    bounce = -3 * cos(2 * phase) * activity + 5 * sin(2 * phase) * sprint
    dog = complex(distance, GROUND - 30 + bounce + 5 * crouch)
    legs = gallop_legs(
        DogRig(), dog, 48, lambda _x: GROUND, support=0.51 - 0.22 * sprint, settle=ease(t, 126, 140)
    )

    collar = dog + complex(17, -12)
    lift = ease(t, 58, 72) - ease(t, 111, 130)
    seated = ease(t, 114, 133)
    recoil = sin(pi * ease(t, 129, 142))
    inhale = sin(t * pi / 31)
    hips_y = GROUND - 70 - 61 * lift + 53 * seated + 2.2 * recoil
    hips_y += 2 * sin(walk / 6) * (1 - ease(t, 40, 51)) + 0.8 * inhale * seated
    grip_y = hips_y - 12 + 21 * lift - 15 * seated
    tight = ease(t, 43, 58) - ease(t, 121, 147)
    dx_taut = sqrt(LEASH**2 - (grip_y - collar.imag) ** 2)
    hand = complex(collar.real - (dx_taut - (1 - tight) * 29), grip_y)
    reach = 24 + 28 * tight - 9 * seated
    hip = complex(hand.real - reach, hips_y)
    shoulder = hip + complex(4 + 16 * lift - 12 * seated, -46 + 19 * lift + 5 * seated)
    face = shoulder + complex(1 + 5 * lift, -24)
    feet = []
    for i in range(2):
        stride = gait(hip.real, (-5, 6)[i], (0.08, 0.58)[i], 43, GROUND - 1)
        trail = hip + complex(
            -46 - 7 * i + 7 * sin(t / 6 + i * pi), -7 + 34 * i + 8 * cos(t / 7 + i * pi)
        )
        foot = stride.tip + (trail - stride.tip) * lift
        rest = hip + complex(34 + 22 * i, GROUND - 1 - hips_y)
        feet.append(foot + (rest - foot) * seated)
    free_hand = shoulder + complex(-17 - 20 * lift, 31 - 61 * lift)
    rueful = ease(t, 137, 162)
    free_hand += (face + complex(-14, 9) - free_hand) * rueful
    look_back = ease(t, 126, 149)
    return Pose(
        t,
        dog,
        tuple(Paw(leg.tip, leg.planted) for leg in legs),
        leash(hand, collar),
        hip,
        shoulder,
        face,
        tuple(feet),
        free_hand,
        lift,
        seated,
        look_back,
        (face.real + dog.real + 27) / 2,
        legs,
    )
