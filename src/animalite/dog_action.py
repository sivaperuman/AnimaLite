"""Frame-indexed run, stop and pivot. Distances are in trunk lengths before projection."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, cos, pi, sin

from pydantic import Field, model_validator

from animalite.contracts.base import Contract
from animalite.gallop import Leg, bend_joint
from animalite.gallop import ramp as ramp
from animalite.gallop_guide import GallopGuide


def unit(value: float) -> float:
    return min(1.0, max(0.0, value))


class RunAction(Contract):
    launch_frame: int = Field(ge=0)
    acceleration_frames: int = Field(ge=2)
    brake_frame: int = Field(ge=0)
    braking_frames: int = Field(ge=2)
    turn_frames: int = Field(default=16, ge=6)

    pose_guide: GallopGuide | None = None

    def first_touch_frame(self, guide: GallopGuide) -> int:
        source_ratio = (guide.landing.frame - guide.launch_frame) / (
            guide.reach.frame - guide.launch_frame
        )
        # Reserve at least one frame after reach, including very short launches.
        return self.launch_frame + max(
            self.acceleration_frames + 1, round(self.acceleration_frames * source_ratio)
        )

    @property
    def stop_frame(self) -> int:
        return self.brake_frame + self.braking_frames

    @property
    def settled_frame(self) -> int:
        return self.stop_frame + self.turn_frames

    @model_validator(mode="after")
    def ordered(self) -> RunAction:
        if self.launch_frame + self.acceleration_frames > self.brake_frame:
            raise ValueError("acceleration must finish before braking")
        if self.pose_guide and self.first_touch_frame(self.pose_guide) >= self.brake_frame:
            raise ValueError("guided forepaw landing must precede braking")
        return self


@dataclass(frozen=True)
class ActionSample:
    distance: float
    activity: float
    turn: float
    stage: str
    pitch: float


def sample_action(action: RunAction, index: int, speed: float) -> ActionSample:
    # Integral of smoothstep velocity; distance and velocity both join continuously.
    elapsed = index - action.launch_frame
    if elapsed < 0:
        return ActionSample(0, 0, 0, "stand", 0)
    a = action.acceleration_frames
    if elapsed < a:
        t = elapsed / a
        return ActionSample(
            speed / 24 * a * (t**3 - 0.5 * t**4), ramp(t), 0, "launch", -0.22 * sin(pi * t)
        )
    cruise = action.brake_frame - action.launch_frame - a
    full = speed / 24
    if index < action.brake_frame:
        return ActionSample(full * (elapsed - a / 2), 1, 0, "gallop", 0)
    b = action.braking_frames
    t = unit((index - action.brake_frame) / b)
    distance = full * (a / 2 + cruise + b * (t - t**3 + 0.5 * t**4))
    if index < action.stop_frame:
        return ActionSample(distance, 1 - ramp(t), 0, "brake", 0.26 * sin(pi * t))
    turning = ramp((index - action.stop_frame) / action.turn_frames)
    return ActionSample(
        distance, 0, turning, "turn" if index < action.settled_frame else "settle", 0
    )


def stance_foot(
    distance: float,
    total: float,
    stride: float,
    offset: float,
    index: int,
    length: float,
    height: float,
    floor: float,
    fore_shift: float = 0.0,
    first_touch: float | None = None,
) -> tuple[complex, bool]:
    """Connect the parked footprints to complete stance intervals in travel coordinates."""
    shift = (0.55, 0.09, 0.66, 0.20)[index]
    margin = min(stride * 0.14, total * 0.23)
    start_hold = margin * (0.25 if index in (0, 3) else 1)
    end_hold = total - margin * (1 if index in (0, 3) else 0.25)
    previous_end, previous_x = start_hold, offset
    if distance <= start_hold:
        return complex(offset, floor), True
    if first_touch is not None and index % 2:
        # Lead paw arrives at the anchored frame. Stagger its partner slightly.
        lead = first_touch + (0.055 * stride if index == 1 else 0)
        first_x = offset + lead + 0.15 * stride + 0.075 * length + fore_shift
        release = min(lead + 0.23 * stride, end_hold)
        if start_hold < lead < release:
            if distance < lead:
                return swing_foot(distance, start_hold, offset, lead, first_x, height * 0.52, floor)
            if distance <= release:
                return complex(first_x, floor), True
            previous_end, previous_x = release, first_x
    for k in range(ceil(total / stride) + 2):
        begin = (k - shift) * stride
        end = begin + 0.30 * stride
        if begin < previous_end + 0.18 * stride or end > end_hold - 0.18 * stride:
            continue
        contact = offset + begin + 0.15 * stride + (1 if index % 2 else -1) * 0.075 * length
        if index % 2:
            contact += fore_shift
        if distance < begin:
            break
        if distance <= end:
            return complex(contact, floor), True
        previous_end, previous_x = end, contact
    else:
        begin, contact = end_hold, total + offset
    if distance >= end_hold:
        return complex(total + offset, floor), True
    return swing_foot(
        distance,
        previous_end,
        previous_x,
        begin,
        contact,
        height * (0.52 if index % 2 else 0.64),
        floor,
    )


def swing_foot(
    distance: float,
    previous_end: float,
    previous_x: float,
    begin: float,
    contact: float,
    height: float,
    floor: float,
) -> tuple[complex, bool]:
    t = unit((distance - previous_end) / (begin - previous_end))
    clearance = min(height, 0.48 * abs(contact - previous_x))
    x = previous_x + (contact - previous_x) * (
        t**3 * (10 - 15 * t + 6 * t * t) - 0.065 * sin(2 * pi * t) * sin(pi * t) ** 2
    )
    return complex(x, floor - clearance * sin(pi * t) ** 1.5), False


def back_shape(legs: tuple[Leg, ...], length: float, activity: float) -> float:
    """Flex the trunk when the feet gather and extend when the fore and hind feet separate."""
    fore = (legs[1].tip.real + legs[3].tip.real) * 0.5
    hind = (legs[0].tip.real + legs[2].tip.real) * 0.5
    return 1 + 0.13 * activity * (2 * ramp(((fore - hind) / length - 0.30) / 0.96) - 1)


def articulated_legs(
    legs: tuple[Leg, ...],
    body: complex,
    length: float,
    activity: float,
    pitch: float,
    turn: float,
    total: float,
    stride: float,
    floor_y: float,
    launch_phase: float,
    bound_strength: float,
    guide: GallopGuide | None = None,
    shoulder_height: float = 0.55,
    first_touch: float | None = None,
    landing_beat: float = 1.56,
) -> tuple[tuple[Leg, ...], float]:
    result = []
    fore_shift = 0.0
    if guide:
        default_touchdown = 0.15 * stride + 0.075 * length
        fore_shift = guide.landing.strength * (
            guide.touchdown_offset(shoulder_height) * length - default_touchdown
        )
    footprints = [
        stance_foot(
            body.real,
            total,
            stride,
            leg.root.real - body.real,
            i,
            length,
            floor_y - leg.root.imag,
            floor_y,
            fore_shift,
            first_touch,
        )
        for i, leg in enumerate(legs)
    ]
    # Use the same anatomical pose for the feet and the spine.
    projected = tuple(
        Leg(leg.root, leg.joint, foot + leg.ankle - leg.tip, foot, planted)
        for leg, (foot, planted) in zip(legs, footprints, strict=True)
    )
    bound_beat = launch_phase
    if first_touch is not None and launch_phase > 1:
        bound_beat = 1 + (launch_phase - 1) * 0.56 / (landing_beat - 1)
    projected = launch_bound(projected, length, bound_beat, bound_strength)
    stretch = back_shape(projected, length, activity)
    yaw = cos(pi * turn)
    pivot_feet = (
        [guide.pivot(leg.tip, body.real, length, turn, i) for i, leg in enumerate(projected)]
        if guide and guide.front_strength and turn > 0
        else []
    )
    for i, leg in enumerate(legs):
        dx = leg.root.real - body.real
        depth = (-1 if i < 2 else 1) * 0.095 * length * sin(pi * turn)
        if pivot_feet and guide and turn > 0.80:
            # As the two shoulders exchange depth, keep their projected order in
            # step with the footprints. Their midpoint stays attached to the torso.
            far, near = i % 2, i % 2 + 2
            span = (legs[near].root.real - legs[far].root.real) * stretch * yaw
            span += 0.19 * length * sin(pi * turn)
            sole_span = pivot_feet[near][0].real - pivot_feet[far][0].real
            visible_span = min(0.07 * length, max(-0.07 * length, sole_span))
            blend = ramp((turn - 0.80) / 0.10) * guide.front_strength
            depth += (0.5 if i == near else -0.5) * blend * (visible_span - span)
        root = body + complex(dx * stretch * yaw + depth, leg.root.imag - body.imag + dx * pitch)
        # Diagonal pairs exchange support while turning through the front view.
        step = unit((turn - (0 if i in (0, 3) else 0.44)) / 0.56)
        placed = projected[i]
        foot, planted = placed.tip, placed.planted
        tip = (
            body.real
            + (foot.real - body.real) * (1 - 2 * ramp(step))
            + 1j * (foot.imag - 0.20 * length * sin(pi * step))
        )
        if step == 0:
            tip = foot
        contact = planted and not 0 < step < 1
        if pivot_feet and guide:
            pivot, pivot_contact = pivot_feet[i]
            w = guide.front_strength
            tip = pivot if w == 1 else tip + w * (pivot - tip)
            contact = pivot_contact and (w == 1 or contact)
        ankle = tip + complex((placed.ankle - foot).real * yaw, (placed.ankle - foot).imag)
        reach = abs(leg.joint - leg.root) + abs(leg.ankle - leg.joint)
        side = (1 if i % 2 else -1) * (1 if yaw >= 0 else -1)
        joint = bend_joint(root, ankle, reach, side)
        # At front view the knee projects toward the camera instead of popping sideways.
        midpoint = (root + ankle) * 0.5
        joint = midpoint + (joint - midpoint) * abs(yaw)
        posed = Leg(root, joint, ankle, tip, contact)
        if guide and i % 2 and turn == 0:
            phase = (body.real / stride + (0.09 if i == 1 else 0.20)) % 1
            posed = guide.foreleg(posed, length, floor_y, launch_phase, phase, activity)
        result.append(posed)
    return tuple(result), stretch


def launch_bound(
    legs: tuple[Leg, ...], length: float, beat: float, strength: float = 1
) -> tuple[Leg, ...]:
    """Shape the first suspended stride in units of the acceleration duration."""
    lift = strength * ramp((beat - 0.22) / 0.63) * (1 - ramp((beat - 1.04) / 0.52))
    if lift == 0:
        return legs
    result = []
    for index, leg in enumerate(legs):
        fore = index % 2
        reach = (0.52 if fore else -0.52) + (-0.05 if index < 2 else 0.05)
        end = leg.root + complex(reach, 0.24 if fore else 0.15) * length
        # A bound only raises a paw away from its current surface.
        target = complex(end.real, min(end.imag, leg.tip.imag - 0.07 * length))
        tip = leg.tip + (target - leg.tip) * lift
        ankle = tip + (leg.ankle - leg.tip) * (1 - 0.34 * lift)
        reach_length = abs(leg.joint - leg.root) + abs(leg.joint - leg.ankle)
        joint = bend_joint(leg.root, ankle, reach_length, 1 if fore else -1)
        result.append(Leg(leg.root, joint, ankle, tip, False))
    return tuple(result)
