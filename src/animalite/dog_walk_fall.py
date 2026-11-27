"""Directed fall and recovery, in 144 by 256 portrait picture coordinates at 24 fps.

These sparse poses describe the action. Both the Studio stage and a first-frame cutout
can use them without reading reference video during synthesis.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from itertools import pairwise
from math import cos, pi, sin
from typing import NamedTuple


def ramp(t: float, start: float, stop: float) -> float:
    u = max(0.0, min(1.0, (t - start) / (stop - start)))
    return u * u * (3 - 2 * u)


class Silhouette(NamedTuple):
    face: complex
    neck: complex
    hip: complex
    free: complex
    grip: complex
    far_knee: complex
    near_knee: complex
    far_foot: complex
    near_foot: complex
    dog: complex


# The feet are ankle pivots. Hands remain independent of the free end of the lead.
KEYS = (
    (
        0,
        Silhouette(
            58.2 + 94.4j,
            49.2 + 116j,
            40.5 + 155.5j,
            59 + 153.6j,
            71.6 + 156.4j,
            39 + 181.5j,
            50 + 178.7j,
            35 + 210.8j,
            50.5 + 207.2j,
            90 + 194j,
        ),
    ),
    (
        10,
        Silhouette(
            69 + 106j,
            56 + 126j,
            41 + 162j,
            75 + 168j,
            76 + 182j,
            43 + 183j,
            54 + 181j,
            35 + 209j,
            51 + 207j,
            90 + 194j,
        ),
    ),
    (
        16,
        Silhouette(
            69 + 105j,
            56 + 126j,
            41 + 162j,
            74 + 168j,
            75 + 181j,
            43 + 183j,
            54 + 181j,
            35 + 209j,
            51 + 207j,
            90 + 194j,
        ),
    ),
    (
        23,
        Silhouette(
            48 + 84j,
            46 + 106j,
            43 + 151j,
            28 + 160j,
            61 + 159j,
            39 + 182j,
            49 + 180j,
            35 + 210j,
            50 + 209j,
            90 + 194j,
        ),
    ),
    (
        43,
        Silhouette(
            48 + 84j,
            46 + 106j,
            43 + 151j,
            28 + 160j,
            58 + 159j,
            34 + 181j,
            50 + 182j,
            30 + 210j,
            52 + 209j,
            90 + 194j,
        ),
    ),
    (
        47,
        Silhouette(
            57 + 92j,
            46 + 113j,
            43 + 154j,
            32 + 143j,
            59 + 148j,
            36 + 182j,
            58 + 177j,
            26 + 201j,
            53 + 201j,
            92 + 190j,
        ),
    ),
    (
        51,
        Silhouette(
            83 + 94j,
            66 + 112j,
            43 + 138j,
            24 + 97j,
            99 + 116j,
            30 + 153j,
            45 + 162j,
            11 + 147j,
            27 + 165j,
            94 + 184j,
        ),
    ),
    (
        56,
        Silhouette(
            57 + 90j,
            48 + 109j,
            31 + 134j,
            16 + 79j,
            66 + 131j,
            18 + 145j,
            24 + 150j,
            5 + 134j,
            10 + 140j,
            85 + 184j,
        ),
    ),
    (
        80,
        Silhouette(
            54 + 91j,
            46 + 109j,
            31 + 135j,
            17 + 78j,
            66 + 131j,
            17 + 148j,
            25 + 152j,
            4 + 134j,
            12 + 142j,
            85 + 184j,
        ),
    ),
    (
        100,
        Silhouette(
            48 + 91j,
            42 + 111j,
            24 + 143j,
            11 + 77j,
            59 + 131j,
            16 + 155j,
            37 + 148j,
            1 + 157j,
            37 + 157j,
            82 + 185j,
        ),
    ),
    (
        117,
        Silhouette(
            47 + 109j,
            42 + 125j,
            20 + 133j,
            81 + 105j,
            59 + 139j,
            12 + 129j,
            10 + 135j,
            1 + 122j,
            4 + 127j,
            84 + 182j,
        ),
    ),
    (
        138,
        Silhouette(
            47 + 109j,
            41 + 126j,
            21 + 134j,
            78 + 107j,
            60 + 138j,
            12 + 131j,
            12 + 135j,
            4 + 121j,
            4 + 128j,
            84 + 183j,
        ),
    ),
    (
        143,
        Silhouette(
            55 + 143j,
            48 + 151j,
            23 + 147j,
            90 + 145j,
            69 + 159j,
            13 + 144j,
            14 + 145j,
            8 + 132j,
            19 + 137j,
            96 + 177j,
        ),
    ),
    (
        148,
        Silhouette(
            79 + 191j,
            61 + 198j,
            34 + 193j,
            68 + 216j,
            116 + 206j,
            29 + 181j,
            20 + 193j,
            25 + 173j,
            8 + 182j,
            101 + 166j,
        ),
    ),
    (
        154,
        Silhouette(
            79 + 188.5j,
            60 + 197j,
            35 + 192j,
            68 + 216j,
            116 + 206j,
            30 + 182j,
            18 + 196j,
            26 + 179j,
            6 + 191j,
            101 + 167j,
        ),
    ),
    (
        169,
        Silhouette(
            79 + 188.5j,
            60 + 197j,
            35 + 192j,
            68 + 216j,
            116 + 206j,
            30 + 182j,
            18 + 196j,
            26 + 179j,
            6 + 191j,
            101 + 167j,
        ),
    ),
    (
        175,
        Silhouette(
            71 + 152j,
            60 + 171j,
            43 + 195j,
            71 + 215j,
            95 + 206j,
            30 + 192j,
            44 + 199j,
            19 + 200j,
            42 + 205j,
            101 + 170j,
        ),
    ),
    (
        181,
        Silhouette(
            46 + 134j,
            48 + 156j,
            49 + 195j,
            33 + 200j,
            77 + 155j,
            41 + 204j,
            76 + 181j,
            29 + 202j,
            83 + 208j,
            103 + 171j,
        ),
    ),
    (
        188,
        Silhouette(
            46 + 134j,
            46 + 157j,
            49 + 199j,
            32 + 201j,
            66 + 150j,
            51 + 214j,
            81 + 185j,
            29 + 204j,
            85 + 210j,
            103 + 171j,
        ),
    ),
    (
        239,
        Silhouette(
            46 + 134j,
            47 + 157j,
            49 + 199j,
            32 + 201j,
            80 + 185j,
            51 + 214j,
            81 + 185j,
            29 + 204j,
            85 + 210j,
            104 + 172j,
        ),
    ),
)
KEY_FRAMES = tuple(key for key, _ in KEYS)
PAN_KEYS = (
    (0, 0),
    (46, 0),
    (50, 2.4),
    (55, 33.5),
    (81, 169),
    (97, 237),
    (118, 318),
    (135, 380),
    (141, 411),
    (146, 426.5),
    (239, 426.5),
)


def camera(t: float) -> float:
    for (a, x), (b, y) in pairwise(PAN_KEYS):
        if t <= b:
            return x + (y - x) * (t - a) / (b - a)
    return PAN_KEYS[-1][1]


@dataclass(frozen=True)
class FallBlocking:
    body: Silhouette
    camera: float
    lead_end: complex
    lead_control: complex
    collar: complex
    release: float
    slack: float
    turn: float
    prone: float
    seated: float
    sprint: float
    lift: float
    dog_sit: float


def blocking(t: float) -> FallBlocking:
    i = min(len(KEYS) - 2, max(0, bisect_right(KEY_FRAMES, t) - 1))
    (a, left), (b, right) = KEYS[i], KEYS[i + 1]
    w = ramp(t, a, b)
    body = Silhouette(*(x + (y - x) * w for x, y in zip(left, right, strict=True)))
    sprint = ramp(t, 45, 51) - ramp(t, 140, 146)
    lift = ramp(t, 46, 54) - ramp(t, 142, 148)
    prone = ramp(t, 143, 148) - ramp(t, 169, 180)
    seated = ramp(t, 171, 184)
    turn = ramp(t, 141, 149)
    dog_sit = ramp(t, 196, 205)
    beat = (t - 50) * 2 * pi / 12
    toes = ramp(t, 52, 58) - ramp(t, 109, 118)
    body = body._replace(
        face=body.face
        + complex(0.5 * sin(beat), 1.0 * cos(beat)) * lift
        + 0.65j * sin(t * 0.13) * seated,
        far_foot=body.far_foot + complex(3 * cos(beat), 5 * sin(beat)) * toes,
        near_foot=body.near_foot - complex(4 * cos(beat), 5 * sin(beat)) * toes,
        dog=body.dog + complex(1.8 * sin(beat), -3.6 * cos(beat)) * sprint,
    )
    # During the pause the loop lies on the pavement. After impact the lead
    # curls back to the collar and the character can use both palms to rise.
    slack = ramp(t, 6, 21) - ramp(t, 43, 51)
    release = ramp(t, 140, 148)
    collar = body.dog + complex(-2.4 + 5 * turn, -8.4)
    end = body.grip + ((57 + 211j) - body.grip) * slack
    recoil = 1 - ramp(t, 166, 180)
    curl = complex(-3 - 28 * recoil + 2.5 * recoil * sin((t - 146) * 0.67), -4 * recoil)
    end += (collar + curl - end) * release
    control = (end + collar) / 2 + complex(-5 - 5 * slack, 8 + 12 * slack) * (1 - lift)
    return FallBlocking(
        body,
        camera(t),
        end,
        control,
        collar,
        release,
        slack,
        turn,
        prone,
        seated,
        sprint,
        lift,
        dog_sit,
    )
