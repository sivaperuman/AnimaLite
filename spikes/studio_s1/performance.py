"""Marvel Engineer blocking in stage pixels (y down), indexed at 24 fps."""

import json
from dataclasses import dataclass, replace
from itertools import pairwise
from math import atan2, cos, degrees, pi, radians, sin, sqrt
from pathlib import Path

FRAMES = 288
RIGS = json.loads(Path(__file__).with_name("rigs.json").read_text())


def ease(frame, first, last):
    t = max(0, min(1, (frame - first) / (last - first)))
    return t * t * (3 - 2 * t)


def mix(a, b, t):
    return a + (b - a) * t


def track(frame, *keys):
    value = keys[0][1]
    for (start, a), (end, b) in pairwise(keys):
        value += (b - a) * ease(frame, start, end)
    return value


def rotate(point, degrees):
    return point * complex(cos(radians(degrees)), sin(radians(degrees)))


@dataclass(frozen=True)
class Chain:
    root: complex
    tip: complex
    upper: float
    lower: float
    bend: int

    def joint(self):
        delta = self.tip - self.root
        length = abs(delta)
        if not abs(self.upper - self.lower) < length < self.upper + self.lower:
            raise ValueError(f"Unreachable target {self}")
        along = (self.upper**2 - self.lower**2 + length**2) / (2 * length)
        normal = self.bend * sqrt(max(0, self.upper**2 - along**2))
        return self.root + delta / length * complex(along, normal)

    def controls(self):
        return [
            self.root.real,
            self.root.imag,
            self.tip.real,
            self.tip.imag,
            self.upper,
            self.lower,
            self.bend,
        ]


def rig(name, hip, shoulder, targets):
    roots = {"hip": hip, "shoulder": shoulder}
    return tuple(
        Chain(roots[c["root"]] + c["offset_x"], tip, c["upper"], c["lower"], c["bend"])
        for c, tip in zip(RIGS[name]["chains"], targets, strict=True)
    )


def boot_pitch(frame, start, end):
    phase = ease(frame, start, end)
    # Toe drops on lift-off, heel leads into landing; both ease to a level sole.
    return 15 * sin(2 * pi * phase)


@dataclass(frozen=True)
class Sheet:
    center: complex
    half_width: float
    tilt: float
    unfold: float
    owner: str

    def point(self, x, y):
        return self.center + rotate(complex(x, y), self.tilt)

    @property
    def left(self):
        return self.point(-self.half_width + 2, 8)

    @property
    def right(self):
        return self.point(self.half_width - 2, -8)


def sheet(frame, hip_x):
    lift = ease(frame, 80, 113)
    take = ease(frame, 148, 173)
    unfold = ease(frame, 169, 204)
    snap = sin(pi * ease(frame, 195, 210))
    center = complex(mix(hip_x + 15, 344, lift) + 40 * take, 242 - 14 * lift - 3 * take - 5 * snap)
    return Sheet(
        center,
        16 + 7 * lift + 18 * unfold,
        -10 + 7 * lift + 4 * take - 5 * snap,
        unfold,
        "milo" if frame < 143 else "owner",
    )


def foot(frame, start, end, x0, x1, y):
    phase = ease(frame, start, end)
    return complex(mix(x0, x1, phase), y - 14 * sin(pi * phase))


@dataclass(frozen=True)
class Actor:
    name: str
    hip: complex
    shoulder: complex
    face: complex
    angle: float
    look_x: float
    look_y: float
    emotion: float
    blink: float
    chains: tuple[Chain, Chain, Chain, Chain]  # far leg, near leg, far arm, near arm


def blink(frame, *beats):
    return min(1.0, min(abs(frame - beat) / 2.5 for beat in beats))


def pose(frame):
    if not 0 <= frame < FRAMES:
        raise ValueError("Frame outside acting test")
    far = foot(frame, 32, 55, 231, 291, 305)
    near = foot(frame, 55, 80, 251, 311, 309)
    sway = track(frame, (0, 0), (26, 0), (32, 4), (55, -3), (76, 3), (88, 0))
    hip_x = (far.real + near.real) / 2 + sway
    bounce = 3 * sin(pi * ease(frame, 32, 55)) + 3 * sin(pi * ease(frame, 55, 80))
    proud = ease(frame, 238, 260)
    breathe = sin(frame * pi / 34)
    hip = complex(hip_x, 250 - bounce + 0.55 * breathe)
    lean = track(
        frame,
        (0, 0),
        (25, 0),
        (34, 6),
        (72, 5),
        (84, 1),
        (115, 7),
        (147, 5),
        (169, -2),
        (233, -2),
        (246, -5),
        (265, 1),
    )
    shoulder = hip + complex(lean, -40 - proud * 3)
    paper = sheet(frame, hip_x)
    release_far = ease(frame, 130, 153)
    release_near = ease(frame, 148, 169)
    hand_far = mix(paper.right, shoulder + complex(23, -1 - 3 * breathe), release_far)
    hand_near = mix(paper.left, hip + complex(-17, -3), release_near)
    hand_far = mix(hand_far, shoulder + complex(5, 13), proud)
    angle = track(
        frame,
        (0, -6),
        (27, -6),
        (45, 2),
        (83, 3),
        (115, 9),
        (150, 8),
        (174, 2),
        (215, 4),
        (230, -8),
        (250, -12),
        (269, -5),
    )
    milo = Actor(
        "milo",
        hip,
        shoulder,
        shoulder + rotate(-1j * RIGS["milo"]["head_from_shoulder"], angle),
        angle,
        track(frame, (0, 0.5), (68, 0.5), (84, 1), (113, 0.8), (165, 0.7), (214, 0.9), (242, 0.15)),
        track(
            frame,
            (0, -0.2),
            (22, -0.2),
            (31, -0.85),
            (68, -0.6),
            (91, 0.7),
            (164, 0.7),
            (176, 1),
            (213, -0.1),
            (249, -0.5),
        ),
        proud,
        blink(frame, 20, 78, 154, 222, 267),
        rig("milo", hip, shoulder, (far, near, hand_far, hand_near)),
    )

    recoil = sin(pi * ease(frame, 202, 218))
    anger = ease(frame, 211, 226)
    owner_hip = complex(402 + 2 * recoil, 247 + 0.55 * sin(frame * pi / 39))
    bend = track(
        frame,
        (0, 1),
        (22, 5),
        (38, 0),
        (105, 0),
        (127, -7),
        (167, -6),
        (197, -8),
        (211, 7),
        (225, -6),
        (242, -3),
    )
    shoulder = owner_hip + complex(bend, -40 + recoil * 2)
    angle = track(
        frame,
        (0, 5),
        (12, 5),
        (25, 14),
        (52, 11),
        (82, 0),
        (117, -6),
        (174, -11),
        (200, -13),
        (213, 12),
        (227, -8),
        (251, -3),
    )
    right_grip = mix(paper.right, paper.point(paper.half_width - 2, 12), ease(frame, 150, 178))
    hand_near = mix(owner_hip + complex(18, -3), right_grip, ease(frame, 103, 130))
    hand_far = mix(owner_hip + complex(-17, -5), paper.left, ease(frame, 119, 143))
    # At transfer both actors briefly touch. Only one owns the moving sheet.
    # Left edge stays pinned while the owner's free hand punctuates the rebuke.
    hand_near = mix(hand_near, shoulder + complex(-30, -19), ease(frame, 209, 225))
    owner = Actor(
        "owner",
        owner_hip,
        shoulder,
        shoulder + rotate(-1j * RIGS["owner"]["head_from_shoulder"], angle),
        angle,
        track(frame, (0, -0.5), (100, -0.5), (116, -1), (166, -0.6), (193, 0.2), (213, -1)),
        track(
            frame,
            (0, 0.25),
            (9, 0.25),
            (15, -1),
            (73, -1),
            (81, 0),
            (120, 0.8),
            (201, 1),
            (214, -0.3),
        ),
        anger,
        blink(frame, 46, 102, 187, 207, 251),
        rig(
            "owner",
            owner_hip,
            shoulder,
            (complex(417, 305), complex(392, 309), hand_far, hand_near),
        ),
    )
    return milo, owner, paper


def camera(frame):
    close = ease(frame, 103, 169) - 0.56 * ease(frame, 207, 240)
    zoom = 1 + 0.77 * close
    return zoom, mix(320, 358, close), mix(180, 207, close)


def inspector_pose(frame):
    """Keep the free wrist on a supported arc as it leaves the unfolding plan."""
    milo, actor, paper = pose(frame)
    if frame >= 209:
        start = pose(209)[1].chains[3]
        initial = start.tip - start.root
        final = complex(-37, -19)
        travel = ease(frame, 209, 239)
        start_angle = degrees(atan2(initial.imag, initial.real))
        end_angle = 360 + degrees(atan2(final.imag, final.real))
        radius = mix(abs(initial), abs(final), travel) + 3 * sin(pi * travel)
        extension = 5 * (ease(frame, 228, 240) - ease(frame, 240, 251))
        arm = actor.chains[3]
        offset = rotate(radius + extension, mix(start_angle, end_angle, travel))
        actor = replace(actor, chains=(*actor.chains[:3], replace(arm, tip=arm.root + offset)))
    lead = 1.8 * (ease(frame, 180, 191) - ease(frame, 191, 204))
    lead -= 3 * (ease(frame, 205, 213) - ease(frame, 213, 226))
    settle = 2 * (ease(frame, 225, 237) - ease(frame, 237, 251))
    return (
        milo,
        replace(
            actor,
            angle=actor.angle + lead + settle,
            face=actor.face + complex(lead * 0.32, settle * 0.32),
        ),
        paper,
    )


def inspector_eyes(frame):
    """Head-local gaze (-1..1 on each axis) and lid openness (0..1)."""
    # Track the fold briefly, fix on the roof, then look at Milo before recoiling.
    x = track(
        frame,
        (0, -0.72),
        (114, -0.72),
        (120, -0.15),
        (169, -0.15),
        (177, 0.14),
        (197, 0.14),
        (201, -0.94),
    )
    y = track(
        frame,
        (0, -0.23),
        (114, -0.23),
        (120, 0.65),
        (169, 0.65),
        (177, 0.98),
        (197, 0.98),
        (201, -0.12),
    )
    return x, y, blink(frame, 48, 103, 167, 243, 278)


def supported_grips(frame, paper):
    """Independent world-space targets for each hand carrying the folding sheet."""
    grips = {}
    if frame <= 130:
        grips["milo", 0] = paper.right
    if frame <= 148:
        grips["milo", 1] = paper.left
    if frame >= 143:
        grips["owner", 0] = paper.left
    if 130 <= frame <= 209:
        grips["owner", 1] = mix(
            paper.right, paper.point(paper.half_width - 2, 12), ease(frame, 150, 178)
        )
    return grips
