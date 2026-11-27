"""Sparse, reusable reference landmarks for a Studio quadruped performance."""

from __future__ import annotations

from itertools import pairwise
from math import copysign, cos, pi, sin, sqrt
from typing import Annotated

from pydantic import Field, model_validator

from animalite.contracts.base import Contract
from animalite.gallop import Leg, ramp

Coordinate = Annotated[float, Field(ge=-100000, le=100000, allow_inf_nan=False)]
Point = tuple[Coordinate, Coordinate]
Weight = Annotated[float, Field(ge=0, le=1)]


class ForePose(Contract):
    """Landmarks on one visible foreleg, in source pixels with y pointing down."""

    frame: int = Field(ge=0)
    hip: Point
    shoulder: Point
    elbow: Point
    wrist: Point
    paw: Point
    strength: Weight = 1.0

    @model_validator(mode="after")
    def distinct(self) -> ForePose:
        if self.hip[0] == self.shoulder[0]:
            raise ValueError("side reference needs a horizontal facing direction")
        points = [complex(*p) for p in (self.shoulder, self.elbow, self.wrist, self.paw)]
        if any(abs(a - b) < 1e-6 for a, b in pairwise(points)) or abs(points[0] - points[2]) < 1e-6:
            raise ValueError("side reference needs distinct limb landmarks")
        if abs(points[3] - points[2]) > 0.65 * abs(complex(*self.hip) - points[0]):
            raise ValueError("paw segment exceeds the reference trunk")
        return self

    def proportions(self) -> tuple[complex, complex, float]:
        hip, shoulder, elbow, wrist, paw = (
            complex(*p) for p in (self.hip, self.shoulder, self.elbow, self.wrist, self.paw)
        )
        upper, lower = abs(elbow - shoulder), abs(wrist - elbow)
        facing = 1 if shoulder.real > hip.real else -1

        def orient(v: complex) -> complex:
            return complex(v.real * facing, v.imag)

        return (
            orient(wrist - shoulder) / (upper + lower),
            orient(paw - wrist) / abs(shoulder - hip),
            upper / (upper + lower),
        )


class GallopGuide(Contract):
    launch_frame: int = Field(ge=0, description="First frame of launch in the source clip")
    reach: ForePose
    landing: ForePose
    front_half_width: float = Field(gt=0, le=0.35, description="Paw lane offset in trunk lengths")
    front_strength: Weight = 1.0

    @model_validator(mode="after")
    def ordered(self) -> GallopGuide:
        if not self.launch_frame < self.reach.frame < self.landing.frame:
            raise ValueError("expected launch, reach, then landing in the source clip")
        if self.landing.wrist[1] <= self.landing.shoulder[1]:
            raise ValueError("the landing wrist must be below the shoulder")
        return self

    def touchdown_offset(self, shoulder_height: float) -> float:
        """Horizontal sole offset at first contact, scaled to a different dog's height."""
        axis, pad, _ = self.landing.proportions()
        offset = pad.real + (shoulder_height - pad.imag) * axis.real / axis.imag
        return min(shoulder_height, max(-shoulder_height, offset))

    def foreleg(
        self, leg: Leg, length: float, floor_y: float, beat: float, phase: float, activity: float
    ) -> Leg:
        """Aim an airborne limb at reach, then keep the sole on its solved contact."""
        if activity <= 0 or beat <= 0:
            return leg
        landing_beat = (self.landing.frame - self.launch_frame) / (
            self.reach.frame - self.launch_frame
        )
        # For later strides, reinforce late swing and release softly into stance.
        if beat <= landing_beat:
            up = ramp(beat)
            down = ramp((beat - 1) / (landing_beat - 1))
            reaching = up * (1 - down)
            landing = down
        else:
            swing = (phase - 0.30) / 0.70
            reaching = ramp(swing / 0.63) * (1 - ramp((swing - 0.63) / 0.37))
            onset = ramp((beat - landing_beat) / 0.6)
            reaching *= onset
            landing = 1 - reaching
        rw = self.reach.strength * reaching * activity
        lw = self.landing.strength * landing * activity
        if rw + lw <= 0:
            return leg
        aim, reach_pad, reach_ratio = self.reach.proportions()
        _, land_pad, land_ratio = self.landing.proportions()
        chain = abs(leg.joint - leg.root) + abs(leg.ankle - leg.joint)
        pad = leg.tip - leg.ankle
        pad += rw * (reach_pad * length - pad) + lw * (land_pad * length - pad)
        tip = leg.tip
        if not leg.planted:
            target = leg.root + aim * chain + pad
            # Keep a visible airborne sole, including on short-legged characters.
            ceiling = floor_y - max(0.06 * length, 0.75 * (floor_y - tip.imag))
            if target.imag > ceiling:
                dy = ceiling - pad.imag - leg.root.imag
                dx = sqrt(max(0.0, abs(aim * chain) ** 2 - dy**2))
                target = complex(leg.root.real + copysign(dx, aim.real) + pad.real, ceiling)
            clearance = ramp((floor_y - tip.imag) / (0.10 * length))
            tip += rw * clearance * (target - tip)
        ankle = tip - pad
        axis = ankle - leg.root
        span = abs(axis)
        if span < 1e-8:
            return Leg(leg.root, leg.joint, ankle, tip, leg.planted)
        ratio = 0.5 + rw * (reach_ratio - 0.5) + lw * (land_ratio - 0.5)
        upper, lower = chain * ratio, chain * (1 - ratio)
        along = min(span, max(0.0, (upper**2 - lower**2 + span**2) / (2 * span)))
        offset = sqrt(max(0.0, upper**2 - along**2))
        joint = leg.root + axis / span * complex(along, offset)
        return Leg(leg.root, joint, ankle, tip, leg.planted)

    def pivot(
        self, start: complex, center: float, length: float, turn: float, index: int
    ) -> tuple[complex, bool]:
        """Step into four front-view footprints, then step out facing the other way."""
        side = -1 if index < 2 else 1
        lane = self.front_half_width * (1 if index % 2 else 0.70)
        middle = complex(center + side * lane * length, start.imag)
        end = complex(2 * center - start.real, start.imag)
        if turn <= 0.5:
            a, b, t = start, middle, turn / 0.36
        else:
            a, b, t = middle, end, (turn - 0.64) / 0.34
        # Move the outward paw first so that a planted partner stays inside its lane.
        lead = index in (1, 2)
        step = max(0.0, min(1.0, (t - (0 if lead else 0.43)) / 0.57))
        if step == 0 or step == 1:
            return (a if step == 0 else b), True
        lift = min(length * 0.14, abs(b - a) * 0.5)
        return a + (b - a) * (0.5 - 0.5 * cos(pi * step)) - 1j * lift * sin(pi * step) ** 2, False
