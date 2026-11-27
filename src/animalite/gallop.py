"""One distance-driven, side-view quadruped gait. Coordinates are world pixels, y down.

Every leg carries its anatomical pivots and the actual ground contact. Project
these points together for either facing direction; the camera never enters the solver.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from math import cos, floor, hypot, pi, sin, sqrt

from pydantic import Field

from animalite.contracts.base import Contract


class DogRig(Contract):
    """Hip/shoulder heights as fractions of trunk length; art and scale are independent."""

    shoulder_height: float = Field(default=0.55, ge=0.35, le=1.05)
    hip_height: float = Field(default=0.53, ge=0.35, le=1.05)
    root_spacing: float = Field(default=0.62, ge=0.43, le=0.82)


@dataclass(frozen=True)
class Leg:
    root: complex
    joint: complex
    ankle: complex
    tip: complex
    planted: bool


def stride_length(rig: DogRig, length: float, extension: float = 1.0) -> float:
    return length * (0.88 + 1.52 * min(rig.shoulder_height, rig.hip_height)) * extension


def bend_joint(root: complex, ankle: complex, reach: float, side: int) -> complex:
    axis = ankle - root
    span = abs(axis)
    if span < 1e-8:
        return root + side * reach * 0.5
    # Equal-length upper and lower links. Collinear at full extension.
    offset = sqrt(max(0.0, (reach * 0.5) ** 2 - (span * 0.5) ** 2))
    return (root + ankle) * 0.5 + side * 1j * axis / span * offset


def gallop_legs(
    rig: DogRig,
    body: complex,
    length: float,
    ground: Callable[[float], float],
    *,
    origin: float = 0,
    extension: float = 1,
    support: float = 0.30,
    active: float = 1,
    rest_center: float = 0,
    settle: float = 0,
) -> tuple[Leg, ...]:
    """Evaluate far hind, far fore, near hind, near fore without previous-frame state.

    origin fixes the phase in world space. active blends from a fixed standing
    footprint on launch/braking. settle lowers a swing paw after travel stops.
    """
    stride = stride_length(rig, length, extension)
    mean_height = (rig.hip_height + rig.shoulder_height) * 0.5
    legs = []
    for index, shift in enumerate((0.55, 0.09, 0.66, 0.20)):
        fore = index % 2 == 1
        sign = 1 if fore else -1
        height = rig.shoulder_height if fore else rig.hip_height
        offset = (sign * rig.root_spacing * 0.5 + (-0.025 if index < 2 else 0.025)) * length
        root = body + complex(offset, (mean_height - height) * length)
        cycle = (body.real - origin) / stride + shift
        step = floor(cycle)
        phase = cycle - step
        # Fixed mid-stance placement, independent of the changing support duration.
        contact = origin + (step - shift + 0.15) * stride + offset + sign * 0.075 * length
        swing = max(0.0, (phase - support) / (1 - support))
        smooth = swing**3 * (10 - 15 * swing + 6 * swing**2)
        reach = -0.065 * sin(2 * pi * swing) * sin(pi * swing) ** 2
        foot_x = (1 - active) * (rest_center + offset) + active * (
            contact + stride * (smooth + reach)
        )
        clearance = height * length * (0.52 if fore else 0.64)
        lift = active * (1 - settle) * clearance * sin(pi * swing) ** 1.5
        tip = complex(foot_x, ground(foot_x) - lift)
        ankle = tip + complex(-0.094 * length, -0.12 * height * length)
        joint = bend_joint(
            root, ankle, length * hypot(0.91 * height, 0.56 * extension), 1 if fore else -1
        )
        planted = active == 0 or (active == 1 and (phase <= support or settle == 1))
        legs.append(Leg(root, joint, ankle, tip, planted))
    return tuple(legs)


def torso_bounce(distance: float, stride: float, length: float) -> float:
    return length * (
        0.040 * cos(2 * pi * distance / stride) + 0.020 * cos(4 * pi * distance / stride)
    )
