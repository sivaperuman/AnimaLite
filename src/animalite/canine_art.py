"""Side-on dog artwork. The same anatomical landmarks drive both drawing treatments."""

from __future__ import annotations

from itertools import pairwise
from math import pi, sin

from animalite.canine import DogDesign, GallopFrame, GallopShot
from animalite.dog_walk_art import ellipse, path, xy

INK = "#332e36"


def countryside(width: float, frame: GallopFrame, ink: bool, has_backdrop: bool) -> str:
    pan = frame.facing * frame.camera
    out: list[str] = []
    if not has_backdrop:
        out = ['<rect width="100%" height="360" fill="#f9f5e9"/>']
        for layer, col in ((0.13, "#e0e5d8"), (0.25, "#cbd7c7")):
            ridge = []
            for column in range(-5, int(width) + 10, 5):
                y = (
                    151
                    + 28 * sin((column + pan * layer) * 0.010)
                    + 13 * sin((column + pan * layer) * 0.022)
                )
                ridge.append(f"{column},{y:.2f}")
            out.append(f'<polygon points="0,215 {" ".join(ridge)} {width},215" fill="{col}"/>')
        out.append(f'<rect y="202" width="{width}" height="158" fill="#e8ddc4"/>')
        for idx in range(-2, int(width / 60) + 3):
            x = idx * 60 - pan * 0.49 % 60
            out.append(path(f"M{x} 214v-27m0 9l61 -2", "#a39579", 2))
    for k in range(-2, int(width / 41) + 3):
        index = k + int(pan // 41)
        x = k * 41 - pan % 41
        y = frame.floor_y + 7 + (index * 17 % 39)
        col = "#736b5d" if ink else "#90744d"
        out.append(path(f"M{x:.2f} {y:.2f}q4 -2 8 -.6m6 1.2 2 -.5", col, 0.9))
    return "".join(out)


def painted_leg(joints: tuple[complex, ...], width: float, row: int, facing: int, far: bool) -> str:
    """Pose the three painted pieces. The paw keeps a horizontal sole."""
    out = ['<g filter="url(#farLeg)">' if far else "<g>"]
    for column, (a, b) in enumerate(pairwise(joints)):
        axis = (b - a) / 80
        # The transverse direction follows the bone, except at the planted sole.
        cross = complex(1, 0) if column == 2 else -1j * axis / max(abs(axis), 1e-8)
        cross *= facing * width / 128
        origin = a - cross * 64 - axis * 24
        out.append(
            f'<g transform="matrix({cross.real:.5f} {cross.imag:.5f} '
            f'{axis.real:.5f} {axis.imag:.5f} {origin.real:.4f} {origin.imag:.4f})">'
            f'<svg width="128" height="128" viewBox="{column * 128} {row * 128} 128 128" '
            'overflow="hidden"><use xlink:href="#legAtlas"/></svg></g>'
        )
    return "".join(out) + "</g>"


def dog_art(
    frame: GallopFrame,
    dog: DogDesign,
    shot: GallopShot,
    head_uri: str,
    body_uri: str = "",
    skin_uri: str = "",
) -> str:
    ink = shot.look == "ink"
    grey = dog.shadow if not ink else "#eee9de"
    coat = dog.coat if not ink else "#fffdf6"
    outline = INK if ink else "#473c42"
    hound = dog.silhouette == "sighthound"
    stride = 2 * pi * frame.phase
    root = frame.body
    L = frame.length

    def local(p: complex) -> complex:
        return (p - root) * 100 / L

    def shape(d: str, fill: str, w: float = 1.6) -> str:
        return path(d, outline, w, fill)

    scale = L / 100
    center = frame.screen(root)
    out = [
        f'<g transform="translate({xy(center)}) scale({frame.facing * scale:.5f},{scale:.5f})" '
        'stroke-linecap="round" stroke-linejoin="round">'
    ]
    # Draw only the articulated lower limbs as strokes. Their anchors and contact
    # pad centers map back to the same exported skeleton in either style.
    if skin_uri:
        out.append(
            f'<defs><image id="legAtlas" width="384" height="512" preserveAspectRatio="none" '
            f'xlink:href="{skin_uri}"/><filter id="farLeg" color-interpolation-filters="sRGB">'
            '<feColorMatrix type="matrix" '
            'values=".75 0 0 0 0  0 .72 0 0 0  0 0 .72 0 0  0 0 0 1 0"/>'
            "</filter></defs>"
        )
    guided_turn = bool(
        shot.performance
        and shot.performance.pose_guide
        and shot.performance.pose_guide.front_strength
    )
    order = (0, 2, 1, 3) if guided_turn and 0.36 <= frame.turn <= 0.64 else (0, 1, 2, 3)
    for i in order:
        leg = frame.legs[i]
        a, b, c, d = (local(p) for p in (leg.root, leg.joint, leg.ankle, leg.tip))
        far = i < 2
        if skin_uri and dog.leg_drawing:
            fore = i % 2 == 1
            row = (0 if fore else 1) + (2 if 0.36 <= frame.turn <= 0.64 else 0)
            width = dog.leg_drawing.fore_width if fore else dog.leg_drawing.hind_width
            facing = 1 if frame.turn <= 0.5 or row >= 2 else -1
            out.append(
                painted_leg((a, b, c, d), 100 * width * (0.9 if far else 1), row, facing, far)
            )
            continue
        thick = (6.0 if hound else 7.8) * (0.87 if far else 1)
        legcolor = grey if far else coat
        top = f"M{xy(a)}L{xy(b)}"
        shin = f"M{xy(b)}L{xy(c)}L{xy(d - 1.8j)}"
        if ink:
            out.append(path(top, outline, 2.65 if not far else 2.05))
            out.append(path(shin, outline, 2.30 if not far else 1.8))
        else:
            out.extend(
                (
                    path(top, outline, thick + 2),
                    path(shin, outline, thick * 0.69 + 1.8),
                    path(top, legcolor, thick),
                    path(shin, legcolor, thick * 0.69),
                )
            )
        out.append(ellipse(d - 1.8j, 3.9 if hound else 4.35, 1.8, outline))
    if body_uri:
        key = frame.body_key()
        art = dog.body_drawings[key]
        size = 100 * art.size_in_trunks
        pin = local(frame.collar(dog))
        sign = 1 if frame.turn <= 0.5 or key == "front" else -1
        width_scale = (frame.stretch if key in ("extended", "compressed") else 1) * sign
        color_filter = ""
        if ink and not art.ink_image:
            out.append(
                '<defs><filter id="inkCel" color-interpolation-filters="sRGB">'
                '<feColorMatrix type="saturate" values="0"/>'
                "<feComponentTransfer>"
                + "".join(
                    f'<feFunc{c} type="table" tableValues=".12 .23 .61 .84 .94 .98 1"/>'
                    for c in "RGB"
                )
                + "</feComponentTransfer></filter></defs>"
            )
            color_filter = ' filter="url(#inkCel)"'
        out.append(
            f'<g transform="translate({xy(pin)}) '
            f'matrix({width_scale:.4f} {frame.pitch:.4f} 0 1 0 0)">'
            f'<image x="{-art.anchor_x * size:.3f}" y="{-art.anchor_y * size:.3f}" '
            f'width="{size}" height="{size}" xlink:href="{body_uri}"{color_filter}/></g></g>'
        )
        return "".join(out)
    if 0.28 <= frame.turn <= 0.72:
        pin = local(frame.collar(dog))
        out.extend(
            (
                ellipse(0j, 22, 23, outline),
                ellipse(0j, 20, 21, coat),
                ellipse(pin - 14j, 23, 21, outline),
                ellipse(pin - 14j, 21.5, 19.5, coat),
            )
        )
        for sign in (-1, 1):
            ear_center = pin + complex(sign * 19, -22)
            out.extend(
                (
                    ellipse(ear_center, 7, 11, outline),
                    ellipse(ear_center, 5.8, 9.5, grey),
                    ellipse(pin + complex(sign * 8, -16), 2.1, 2.8, outline),
                )
            )
        out.extend(
            (
                ellipse(pin - 8j, 4, 3, outline),
                path(f"M{xy(pin - 10 + 1j)}q9 5 19 0", dog.collar, 3),
                ellipse(pin, 1.9, 2.3, "#bf9252"),
                "</g>",
            )
        )
        return "".join(out)
    # Limb points are already projected. The same deformation places the spine and neck.
    out.append(f'<g transform="matrix({frame.yaw * frame.stretch:.5f} {frame.pitch:.5f} 0 1 0 0)">')
    flick = 5 * sin(stride - 0.7)
    tilt = 3.8 * sin(stride + 0.2)
    if hound:
        tail = (
            f"M-38 -15 Q-57 -26 -77 {-18 + flick:.2f} "
            f"T-94 {-21 + flick:.2f} Q-84 {-8 + flick:.2f} -66 -14 T-43 -2Z"
        )
        torso = (
            "M-47 -9Q-43 -25 -22 -25Q0 -21 16 -25Q34 -31 42 -23Q46 -14 43 -1"
            "Q38 21 26 20Q15 18 10 9Q-1 -2 -19 0Q-28 1 -31 12Q-41 17 -46 8Q-52 0 -47 -9Z"
        )
    else:
        tail = (
            f"M-39 -10Q-65 {-13 + flick:.2f} -65 {-38 + flick:.2f}"
            f"Q-61 {-44 + flick:.2f} -58 -32Q-54 -20 -39 -21Z"
        )
        torso = (
            "M-45 -11Q-44 -26 -21 -26Q3 -27 24 -24Q38 -28 45 -16Q52 -2 40 10"
            "Q32 18 14 17Q-9 18 -23 15Q-39 20 -45 10Q-51 0 -45 -11Z"
        )
    out.extend((shape(tail, grey), shape(torso, coat, 1.7 if ink else 1.55)))
    if not ink:
        out.append(
            path(
                "M-43 4Q-27 12 -18 9Q2 12 17 8Q27 10 37 5Q33 15 17 15Q-5 16 -20 13Q-36 18 -43 7Z"
                if not hound
                else (
                    "M-40 4Q-29 -4 -18 -3Q-1 -8 9 2Q28 19 39 2"
                    "Q35 24 23 17Q15 14 8 7Q-1 -2 -19 0Q-31 2 -33 10Z"
                ),
                "none",
                0,
                grey,
            )
        )
    if hound:
        out.append(shape("M13 -23Q29 -31 38 -42L46 -28Q41 -13 34 -5Q23 -4 16 -10Z", coat))
        neck = complex(38, -33)
    else:
        out.append(shape("M20 -18Q25 -29 33 -35L47 -24Q47 -12 37 -6Q25 -7 20 -18Z", coat))
        neck = complex(36, -25)
    out.append(f'<g transform="translate({xy(neck)}) rotate({tilt:.2f})">')
    if head_uri:
        drawing = dog.head_drawings[shot.look][frame.head_view]
        size = 100 * drawing.size_in_trunks
        out.append(
            f'<image x="{-size * drawing.anchor_x:.3f}" y="{-size * drawing.anchor_y:.3f}" '
            f'width="{size}" height="{size}" xlink:href="{head_uri}"/>'
        )
    else:
        half = frame.head_view == "three-quarter"
        if hound:
            face = (
                (
                    "M-15 -8Q-14 -28 2 -31Q13 -31 19 -20L42 -13"
                    "Q47 -10 42 -5L24 -2Q13 10 -2 8Q-12 5 -15 -8Z"
                )
                if not half
                else "M-15 -8Q-14 -28 3 -31Q17 -31 22 -18L30 -9Q30 -1 19 3Q7 12 -3 7Q-13 4 -15 -8Z"
            )
        else:
            face = (
                (
                    "M-24 -8Q-25 -24 -13 -32Q-4 -39 5 -35L7 -38L11 -34Q27 -32 28 -16"
                    "Q38 -13 36 -3Q34 8 20 12Q3 20 -12 12Q-23 7 -24 -8Z"
                )
                if not half
                else (
                    "M-23 -8Q-26 -25 -10 -33Q-3 -38 7 -35L9 -37"
                    "Q23 -33 25 -20Q32 -12 29 -1Q26 12 12 15Q-11 20 -21 5Z"
                )
            )
        out.append(shape(face, coat))
        earf = 4 * sin(stride - 0.65)
        ear = (
            (
                f"M-8 -25Q-18 {-28 + earf:.2f} -33 {-20 + earf:.2f}"
                f"Q-31 {-8 + earf:.2f} -21 -7Q-14 -4 -8 -17Z"
            )
            if not hound
            else f"M-3 -24Q-14 {-18 + earf:.2f} -24 {-28 + earf:.2f}Q-20 -12 -10 -8Q-5 -10 -3 -24Z"
        )
        out.append(shape(ear, grey if ink else dog.marking, 1.35))
        eye = complex((11 if hound else 17) - (3 if half else 0), -18)
        if half:
            out.append(ellipse(eye - 13 + 0.8j, 1.65, 2.55, outline))
        out.extend(
            (ellipse(eye, 2.0, 3.0, outline), ellipse(eye + 0.55 - 0.95j, 0.72, 0.72, "#fff9ed"))
        )
        nose = complex(
            (42 if hound else 32) if not half else (27 if hound else 23), -10 if hound else -8
        )
        out.append(ellipse(nose, 3.9, 2.8, outline))
        out.append(path(f"M{xy(nose - 0.6 + 2j)}q-.4 7 -8 5q-3 -.6 -4 -2", outline, 1.1))
        if not ink:
            out.append(path(f"M{xy(eye - 4 - 4j)}q3 -2 5 -.7", outline, 0.88))
    out.append("</g>")
    out.append(path(f"M{xy(neck - 10 + 9j)}q8 5 19 0", outline, 5.1))
    out.append(path(f"M{xy(neck - 10 + 9j)}q8 5 19 0", dog.collar, 3.3))
    out.append(ellipse(neck + 5 + 14j, 1.6, 2.55, "#bf9252"))
    out.append("</g></g>")
    return "".join(out)
