"""A hand-held lead with slack, bounded reach and a reaction driven by its load."""

from __future__ import annotations

from dataclasses import dataclass
from math import pi, sin, sqrt

from animalite.canine import DogDesign, GallopFrame, LeadHandler
from animalite.choreography import CharacterDesign
from animalite.dog_action import ramp
from animalite.dog_walk import Leash, leash
from animalite.dog_walk_art import ellipse, limb, path, xy
from animalite.gallop import bend_joint


@dataclass(frozen=True)
class HandlerPose:
    lead: Leash
    shoulder: complex
    hip: complex
    head: complex
    elbow: complex
    feet: tuple[complex, complex]
    tension: float
    surprise: float
    lift: float


class LeadPerformance:
    def __init__(self, config: LeadHandler, actor: CharacterDesign):
        self.config = config
        self.actor = actor
        self.rest_x: float | None = None
        self.lift = 0.0
        self.last_pull = -10000

    def advance(self, f: GallopFrame, dog: DogDesign, index: int) -> HandlerPose:
        L = f.length
        size = L * self.actor.size
        collar = f.collar(dog)
        rope = L * self.config.leash_length
        neutral_y = (
            f.floor_y
            - (dog.rig.shoulder_height + dog.rig.hip_height) * L * 0.5
            + (-0.19 if dog.silhouette == "sighthound" else -0.11) * L
        )
        rest_y = min(neutral_y + 0.55 * rope, max(neutral_y - 0.55 * rope, f.floor_y - 0.96 * size))
        if self.rest_x is None:
            self.rest_x = collar.real - 0.72 * rope
        # When elbow and torso have yielded, excess horizontal demand tows the pelvis.
        dy = collar.imag - rest_y
        horizontal = sqrt(max(0, rope**2 - min(abs(dy), rope) ** 2))
        arm = 0.36 * size * self.actor.limb_scale
        self.rest_x = max(self.rest_x, collar.real - horizontal - arm)
        relaxed = complex(self.rest_x, rest_y)
        delta = collar - relaxed
        demand = abs(delta) / rope
        tension = ramp((demand - 0.93) / 0.17)
        hand = collar - delta / max(1e-9, abs(delta)) * rope if demand > 1 else relaxed
        self.lift += (0.26 if tension > self.lift else 0.17) * (tension - self.lift)
        if tension > 0.65:
            self.last_pull = index
        surprise = max(
            tension, 1 - ramp((index - self.last_pull - self.config.surprise_hold_frames) / 9)
        )
        hip = complex(
            self.rest_x - (0.28 + 0.18 * self.lift) * size,
            f.floor_y - (0.81 + 0.26 * self.lift) * size,
        )
        shoulder = hip + complex(
            (0.03 + 0.29 * self.lift) * size, -(0.52 - 0.18 * self.lift) * size
        )
        head = shoulder + complex(0.08 * size, -0.24 * size)
        elbow = bend_joint(
            shoulder,
            hand,
            max(abs(hand - shoulder), 0.80 * size * self.actor.limb_scale),
            -1 if self.config.hand == "right" else 1,
        )
        feet = tuple(
            complex(
                hip.real + ((-0.10, 0.12)[k] - (0.62, 0.47)[k] * self.lift) * size,
                f.floor_y - self.lift * (0.67 + 0.13 * sin(2 * pi * f.phase + k * pi)) * size,
            )
            for k in range(2)
        )
        return HandlerPose(
            leash(hand, collar, rope),
            shoulder,
            hip,
            head,
            elbow,
            (feet[0], feet[1]),
            tension,
            surprise,
            self.lift,
        )


def draw_handler(
    f: GallopFrame, h: HandlerPose, actor: CharacterDesign, ink: bool, far_grip: bool = False
) -> str:
    # Use the same local frame and the same grip for the hand, arm and lead.
    size = f.length * actor.size

    def loc(p: complex) -> complex:
        return (p - h.hip) * 100 / size

    dark = "#353039"
    sh = loc(h.shoulder)
    head = loc(h.head)
    hand = loc(h.lead.hand)
    coat = "#fff9e9" if ink else actor.shirt
    skin = "#fffbef" if ink else actor.skin
    parts = [
        f'<g transform="translate({xy(f.screen(h.hip))}) '
        f'scale({f.facing * size / 100:.5f},{size / 100:.5f})" '
        'stroke-linecap="round" stroke-linejoin="round">'
    ]
    for i, foot in enumerate(h.feet):
        end = loc(foot)
        knee = end * 0.52 + complex(9 - 23 * h.lift, -4 - 5 * i)
        parts.extend((limb(0j, knee, end - 3j, dark, 4.4), ellipse(end + 2 - 2j, 7.5, 2.7, dark)))
    free = sh + complex(-18 - 30 * h.lift, 43 - 59 * h.lift)
    parts.append(limb(sh, (free + sh) * 0.5 - 9, free, dark, 3.8))
    grip_arm = limb(sh, loc(h.elbow), hand, dark, 4.1)
    if far_grip:
        parts.append(grip_arm)
    parts.append(
        path(f"M{xy(sh - 7)} Q{xy(sh + 8 - 7j)} {xy(sh + 9)}L9,3Q1,9 -11,4Z", dark, 1.8, coat)
    )
    if not far_grip:
        parts.append(grip_arm)
    parts.append(ellipse(hand, 3.8, 4, skin))
    parts.append(ellipse(head, 17, 18, dark))
    parts.append(ellipse(head, 15.5, 16.5, skin))
    hair = (
        "q1 -12 13 -13q12 -2 19 12l-10 -3 -5 4 -1 -5Z"
        if actor.costume == "forelock"
        else "q1 -15 16 -15q13 0 15 11l8 1q3 4 -3 5l-36 1Z"
    )
    parts.append(
        path(f"M{xy(head - 15 - 6j)}" + hair, dark, 1.3, coat if actor.costume == "cap" else dark)
    )
    for x in (1, 10):
        eye = head + complex(x, -2 - 2 * h.surprise)
        parts.extend(
            (
                ellipse(eye, 2.6, 2.7 + 1.2 * h.surprise, "white"),
                ellipse(eye + 0.7, 1.35, 1.65, dark),
            )
        )
    parts.append(ellipse(head + 7 + 8j, 2.8, 0.8 + 3.6 * h.surprise, dark))
    a, b, c = (loc(p) for p in (h.lead.hand, h.lead.control, h.lead.collar))
    parts.append(path(f"M{xy(a)}Q{xy(b)} {xy(c)}", "#864337", 1.85))
    parts.append(ellipse(hand, 2.2, 2.3, skin))
    parts.append("</g>")
    return "".join(parts)
