"""Composite original cut-paper layers at articulated joint positions."""

from math import atan2, degrees, pi, sin
from pathlib import Path
from xml.etree import ElementTree as ET

from performance import boot_pitch, camera, ease

HERE = Path(__file__).resolve().parent
INK = "#263d48"
ET.register_namespace("", "http://www.w3.org/2000/svg")


def cutouts(name):
    # Only the two bundled, author-owned SVG files are parsed.
    root = ET.parse(HERE / f"{name}.svg").getroot()  # noqa: S314
    layers = {}
    for group in root:
        layer = group.attrib.pop("id")
        group.set("stroke", INK)
        group.set("stroke-width", "2")
        layers[layer] = ET.tostring(group, encoding="unicode")
    return layers


SKINS = {name: cutouts(name) for name in ("milo", "owner")}
SITE = (HERE / "site.svg").read_text().split(">", 1)[1].rsplit("</svg>", 1)[0]


def xy(point):
    return f"{point.real:.3f} {point.imag:.3f}"


def place(point, content, angle=0, flip=1):
    return (
        f'<g transform="translate({xy(point)}) rotate({angle:.3f}) scale({flip} 1)">{content}</g>'
    )


def oval(x, y, rx, ry, color):
    return f'<ellipse cx="{x:.3f}" cy="{y:.3f}" rx="{rx:.3f}" ry="{ry:.3f}" fill="{color}"/>'


def line(points, width, color):
    coords = " L".join(xy(p) for p in points)
    return f'<path d="M{coords}" fill="none" stroke="{color}" stroke-width="{width}"/>'


def face(actor, frame):
    milo = actor.name == "milo"
    parts = []
    eye_x = (1, 13) if milo else (-12, 1)
    y = 1
    open_eye = max(0.12, actor.blink)
    for i, x in enumerate(eye_x):
        ry = (5.0 if milo else 4.4) * open_eye
        parts.append(oval(x, y, 4.4, ry, "#fff3db"))
        px = x + actor.look_x * 1.8
        py = y + actor.look_y * open_eye
        parts.append(oval(px, py, 2, 2.9 * open_eye, INK))
        brow_y = y - 8 - (2.0 if i == 1 else 0.5) * (1 - actor.emotion)
        slope = (-1 if i == 1 else 1) * (3 if not milo else -1) * actor.emotion
        parts.append(
            line([complex(x - 4, brow_y - slope), complex(x + 3, brow_y + slope)], 2.3, INK)
        )
    if milo:
        parts.append('<path d="M12 5q5 1 4 4l-4 1" fill="#db895e" stroke="#ad684e"/>')
        grin = 1 + actor.emotion * (4 + 3 * sin(frame * pi / 5) * (1 - ease(frame, 269, 278)))
        parts.append(
            f'<path d="M1 13q6 {grin + 4} 12 -1Q6 {13 + grin + 1} 1 13z" '
            f'fill="#fff3db" stroke="{INK}" stroke-width="1.4"/>'
        )
        parts.append(oval(-5, 9, 3, 1.4, "#e99b6f"))
    else:
        # Wire spectacles, hooked nose and split moustache distinguish the owner in profile.
        parts.append(
            '<path d="M-19-2h13v6q-4 4-10 0zm14 0H8v6Q2 8-3 4zm-2 2h3" '
            'fill="none" stroke="#4b5953" stroke-width="1.2"/>'
        )
        parts.append('<path d="M-9 4l-4 7q1 2 6 0" fill="#ce886c" stroke="#ac705a"/>')
        jaw = actor.emotion * (1 - ease(frame, 231, 240)) * (3 + 2 * sin(frame * pi / 7))
        parts.append(oval(-5, 15, 5, 1.4 + jaw, "#693e3d"))
        parts.append('<path d="M-6 9q-6-3-11 5 7 2 11-1 6 3 13-1-7-6-13-3z" fill="#74746a"/>')
    return "".join(parts)


def limb(chain, joint, end, arm, milo, far):
    shade = "#345264" if far else "#416275"
    if not milo:
        shade = "#525a55" if far else "#626a62"
    skin = ("#d99a68" if far else "#efb077") if milo else ("#c48668" if far else "#dfa17e")
    width = (7 if far else 8.5) if arm else (8.5 if far else 10)
    body = line([chain.root, joint, end], width + 3, INK)
    if arm:
        cuff = joint + 0.30 * (end - joint)
        sleeve = ("#246a88" if far else "#398da7") if milo else ("#834951" if far else "#a95a58")
        body += line([chain.root, joint, cuff], width, sleeve)
        body += line([cuff, end], width - 1, skin)
        body += line(
            [joint + 0.22 * (end - joint), cuff], width + 1, "#b5c8b7" if milo else "#ddc6a0"
        )
    else:
        body += line([chain.root, joint, end], width, shade)
        body += line(
            [joint + 0.79 * (end - joint), joint + 0.89 * (end - joint)],
            width + 1,
            "#769297" if milo else "#889082",
        )
    return body


def actor_layers(actor, joints, frame):
    milo = actor.name == "milo"
    skin = SKINS[actor.name]
    limbs = [
        limb(c, j, e, i >= 2, milo, i % 2 == 0)
        for i, (c, (j, e)) in enumerate(zip(actor.chains, joints, strict=True))
    ]
    pitches = (boot_pitch(frame, 32, 55), boot_pitch(frame, 55, 80)) if milo else (0, 0)
    boots = [
        place(end, skin["boot"], pitch, flip=1 if milo else -1)
        for (_, end), pitch in zip(joints[:2], pitches, strict=True)
    ]
    tilt = degrees(atan2((actor.shoulder - actor.hip).real, -(actor.shoulder - actor.hip).imag))
    # Body artwork grows down from the shoulder. Its local hip follows the root.
    body = place(actor.shoulder, skin["body"], tilt)
    head = place(actor.face, skin["head"] + face(actor, frame), actor.angle)
    neck = line([actor.shoulder, actor.face + 16j], 9, "#c58764")
    parts = [limbs[0], boots[0], limbs[1], boots[1], limbs[2], neck, body, head, limbs[3]]
    return "".join(parts)


# Each hand has a distinct fill so the final raster identifies the carrying hand.
HAND_COLORS = {
    ("milo", 0): "#db9969",
    ("milo", 1): "#f2b478",
    ("owner", 0): "#ce8f70",
    ("owner", 1): "#e5aa82",
}
INSPECTOR_HAND_COLORS = {**HAND_COLORS, ("owner", 0): "#b67b50", ("owner", 1): "#ca8b58"}
PAPER_FILL = "#246b88"
PAPER_EDGE = "#183f54"


def palm(center, milo, point=False, color=None):
    color = color or ("#efb077" if milo else "#dfa17e")
    thumb = "M0-1q-3-5-5-4-2 1 0 5" if milo else "M0-1q3-5 5-4 2 1 0 5"
    fingers = "M2 1l-12-4q-4-1-4 1t11 7" if point else thumb
    return place(
        center,
        f'<g fill="{color}" stroke="{INK}" stroke-width="1.4"><path d="{fingers}"/>'
        f'<ellipse rx="4.8" ry="4.5"/></g>',
    )


def blueprint(paper):
    w = paper.half_width
    crease = 1 - paper.unfold
    h = 21
    kink = 10 * crease
    # Both halves of the facade share the same crease on every frame.
    left, right = -w * 0.74, w * 0.74
    art = [
        f'<path d="M{-w} {-h} Q-4 {-h - 2} 0 {-h + 2 * crease} L{w} {-h + kink / 2} '
        f'L{w} {h} Q6 {h - 3 * crease} 0 {h + crease} L{-w} {h}z" '
        f'fill="{PAPER_FILL}" stroke="{PAPER_EDGE}" stroke-width="2"/>'
    ]
    for y in (-14, -7, 0, 7, 14):
        art.append(line([complex(-w + 2, y), complex(w - 2, y)], 0.45, "#689eab"))
    for x in range(-36, 37, 7):
        if abs(x) < w - 2:
            art.append(line([complex(x, -18), complex(x, 18)], 0.45, "#689eab"))
    ink = "#fff1ce"
    roof_left, roof_right = -12 - 4 * crease, -12 + 10 * crease
    art.append(
        f'<g fill="none" stroke="{ink}" stroke-width="1.5">'
        f'<path d="M{left} 2H{right}v12H{left}z M-3 14V6h6v8 '
        f"M{left} {roof_left}L{right} {roof_right}v9L{left} {roof_left + 9}z "
        f'M{left - 2} {roof_left - 2}L{right + 2} {roof_right - 2}"/>'
        f'<path d="M{left * 0.65} {roof_left + 4}l4 {crease}v3l-4 {-crease}z '
        f'M{right * 0.4} {roof_right + 1}l5 {crease}v3l-5 {-crease}z"/></g>'
    )
    art.append(
        f'<g opacity="{crease:.4f}">'
        '<path d="M-6-21l7 2 6 38-7 2z" fill="#83bac1" opacity=".85"/>'
        '<path d="M-6-21L0 21M6-19l-9 35" fill="none" stroke="#c8dfcf" stroke-width="1.3"/></g>'
    )
    return place(paper.center, "".join(art), paper.tilt)


def svg(frame, pose, joints, width, character="owner", gaze_mode="directed"):
    milo, owner, paper = pose
    zoom, cx, cy = camera(frame)
    layers = [SITE]
    for actor in (milo, owner):
        layers.append(oval(actor.hip.real, 315, 30, 4, "#b69771"))
    for actor, limbs in zip((milo, owner), joints, strict=True):
        if character == "inspector" and actor.name == "owner":
            from inspector_art import inspector_layers

            layers.append(inspector_layers(actor, limbs, frame, gaze_mode))
        else:
            layers.append(actor_layers(actor, limbs, frame))
    layers.append(blueprint(paper))
    for actor, limbs in zip((milo, owner), joints, strict=True):
        for index, (_, end) in enumerate(limbs[2:]):
            colors = INSPECTOR_HAND_COLORS if character == "inspector" else HAND_COLORS
            milo_hand = actor.name == "milo"
            # The fingertips meet the same grip; the palms approach from opposite sides.
            offset = -3.7 if milo_hand else 3.7
            if character == "inspector" and not milo_hand and index == 1:
                extension = ease(frame, 224, 238)
                finger = (
                    f"M1 0 L{-4 - 11 * extension:.2f} {-2 - 4 * extension:.2f} "
                    f"Q{-8 - 11 * extension:.2f} {-2 - 4 * extension:.2f} "
                    f"{-5 - 11 * extension:.2f} {1 - 4 * extension:.2f} L-1 4Z"
                )
                layers.append(
                    place(
                        end + offset,
                        f'<path d="{finger}" fill="{colors[actor.name, index]}" '
                        f'stroke="{INK}" stroke-width="1.3"/>',
                    )
                )
            layers.append(
                palm(
                    end + offset,
                    milo_hand,
                    character == "owner" and not milo_hand and index == 1 and frame >= 224,
                    colors[actor.name, index],
                )
            )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{width * 9 // 16}" '
        'viewBox="0 0 640 360" stroke-linecap="round" stroke-linejoin="round">'
        f'<g transform="translate(320 180) scale({zoom:.5f}) translate({-cx:.4f} {-cy:.4f})">'
        + "".join(layers)
        + "</g></svg>"
    )
