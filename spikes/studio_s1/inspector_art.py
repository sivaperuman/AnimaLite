"""Reusable painted head, coat and boots in the inspector's local coordinates."""

import base64
import io
from functools import lru_cache
from math import atan2, degrees
from pathlib import Path

from artwork import line, place, xy
from performance import ease, inspector_eyes, mix
from PIL import Image, ImageDraw

ASSETS = Path(__file__).with_name("inspector")
# Each expression fits both eye openings to the painted face, in 200 x 240 art units.
# Tuple order: left corner, right corner, upper arch height, lower arch height.
EYES = (
    ((26, 117, 49, 126, 20, 10), (74, 141, 112, 132, 18, 12)),
    ((30, 135, 52, 139, 24, 13), (76, 146, 111, 134, 23, 17)),
    ((27, 128, 46, 137, 11, 6), (66, 142, 105, 137, 9, 10)),
)
EYE_INK = "#36241e"
HEAD_SIZE = (200, 240)


def svg_image(image, x, y, width, height):
    encoded = io.BytesIO()
    image.save(encoded, format="PNG", compress_level=1)
    data = base64.b64encode(encoded.getvalue()).decode("ascii")
    return (
        f'<image xmlns:xlink="http://www.w3.org/1999/xlink" x="{x}" y="{y}" '
        f'width="{width}" height="{height}" preserveAspectRatio="none" '
        f'xlink:href="data:image/png;base64,{data}"/>'
    )


@lru_cache(maxsize=1)
def cutouts():
    with Image.open(ASSETS / "expressions.webp") as sheet:
        size = sheet.height * 5 // 6
        portraits = [
            sheet.crop((i * size, 0, (i + 1) * size, sheet.height)).convert("RGBa")
            for i in range(9)
        ]
    with Image.open(ASSETS / "coat.webp") as coat, Image.open(ASSETS / "boot.webp") as boot:
        return portraits, svg_image(coat, -18, -9, 37, 52), svg_image(boot, -15, -14, 22, 22)


def draw_eye(image, fit, look_x, look_y, openness):
    x0, y0, x1, y1, top, bottom = fit
    width = x1 - x0
    upper, lower = [], []
    for n in range(25):
        t = n / 24
        arch = 4 * t * (1 - t)
        x, y = mix(x0, x1, t), mix(y0, y1, t)
        closed_y = y + bottom * 0.52 * arch
        upper.append((x, mix(closed_y, y - top * arch, openness)))
        lower.append((x, mix(closed_y, y + bottom * arch, openness)))
    mask = Image.new("L", HEAD_SIZE)
    ImageDraw.Draw(mask).polygon([*upper, *reversed(lower)], fill=255)
    fill = Image.new("RGBA", HEAD_SIZE, "#f7e4c4")
    pupil = ImageDraw.Draw(fill)
    cx = mix(x0, x1, 0.49 + 0.26 * look_x)
    cy = (y0 + y1) / 2 + (bottom - top) * 0.35 + (top + bottom) * 0.25 * look_y
    rx, ry = width * 0.21, (top + bottom) * 0.37
    pupil.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill="#50372c")
    pupil.ellipse((cx - rx * 0.66, cy - ry * 0.83, cx + rx * 0.66, cy + ry * 0.83), fill="#251d1c")
    pupil.ellipse((cx - rx * 0.46, cy - ry * 0.56, cx - rx * 0.12, cy - ry * 0.28), fill="#fff5df")
    image.paste(fill, (0, 0), mask)
    pen = ImageDraw.Draw(image)
    pen.line(lower, fill="#795039", width=1)
    pen.line(upper, fill=EYE_INK, width=3)


@lru_cache(maxsize=32)
def painted_head(phase, gaze):
    portraits, _, _ = cutouts()
    plate = phase * 4
    first = int(plate)
    # Interpolate premultiplied colors to keep transparent edges clean.
    image = Image.blend(portraits[first], portraits[min(first + 1, 8)], plate - first)
    image = image.convert("RGBA").resize(HEAD_SIZE, Image.Resampling.BICUBIC)
    key = int(phase)
    for start, end in zip(EYES[key], EYES[min(key + 1, 2)], strict=True):
        fit = [mix(a, b, phase - key) for a, b in zip(start, end, strict=True)]
        draw_eye(image, fit, *gaze)
    return svg_image(image, -27, -39, 51, 59)


def cloth(a, joint, b, shoulder_width, elbow_width, cuff_width, color):
    normal = 1j * (joint - a) / abs(joint - a)
    end_normal = 1j * (b - joint) / abs(b - joint)
    mid = (normal + end_normal) / abs(normal + end_normal)
    path = (
        f"M{xy(a + normal * shoulder_width)} Q{xy((a + joint) * 0.5 + normal * shoulder_width)} "
        f"{xy(joint + mid * elbow_width)} Q{xy((joint + b) * 0.5 + end_normal * elbow_width)} "
        f"{xy(b + end_normal * cuff_width)} L{xy(b - end_normal * cuff_width)} "
        f"Q{xy((joint + b) * 0.5 - end_normal * elbow_width)} {xy(joint - mid * elbow_width)} "
        f"Q{xy((a + joint) * 0.5 - normal * shoulder_width)} {xy(a - normal * shoulder_width)} "
        f"Q{xy(a - (joint - a) * 0.16)} {xy(a + normal * shoulder_width)}Z"
    )
    return f'<path d="{path}" fill="{color}" stroke="#61432c" stroke-width="1"/>'


def inspector_layers(actor, joints, frame, gaze_mode):
    _, coat, boot = cutouts()
    limbs = []
    for i, (chain, (joint, end)) in enumerate(zip(actor.chains, joints, strict=True)):
        if i < 2:
            color = "#405347" if i == 0 else "#536758"
            limb = cloth(chain.root, joint, end, 7.7, 7, 4.6, color) + place(end, boot)
        else:
            cuff = mix(joint, end, 0.8)
            limb = line([cuff, end], 6, "#c18252")
            limb += cloth(chain.root, joint, cuff, 5.8, 4.8, 4, "#b57a2c" if i == 2 else "#d29740")
        limbs.append(limb)
    phase = ease(frame, 176, 194) + ease(frame, 210, 231)
    gaze = inspector_eyes(frame) if gaze_mode == "directed" else (0, 0, 1)
    tilt = degrees(atan2((actor.shoulder - actor.hip).real, -(actor.shoulder - actor.hip).imag))
    neck = line([actor.shoulder, actor.face + 16j], 8, "#b57a4b")
    return "".join(
        [
            *limbs[:3],
            neck,
            place(actor.shoulder, coat, tilt),
            place(actor.face, painted_head(phase, gaze), actor.angle),
            limbs[3],
        ]
    )
