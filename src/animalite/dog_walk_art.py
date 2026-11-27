"""Original layered street, handler and terrier artwork for the Studio action."""

from __future__ import annotations

from math import floor, sin

from animalite.dog_walk import GROUND, DogWalk, Pose, ease, picture_to_stage

INK = "#253645"
LEAD_COLOR = "#e35232"


def xy(p: complex) -> str:
    return f"{p.real:.3f},{p.imag:.3f}"


def ellipse(p: complex, rx: float, ry: float, color: str) -> str:
    return (
        f'<ellipse cx="{p.real:.2f}" cy="{p.imag:.2f}" rx="{rx:.2f}" ry="{ry:.2f}" fill="{color}"/>'
    )


def path(d: str, color: str, width: float, fill: str = "none") -> str:
    return f'<path d="{d}" fill="{fill}" stroke="{color}" stroke-width="{width}"/>'


def limb(start: complex, bend: complex, end: complex, color: str, width: float) -> str:
    return path(f"M{xy(start)} L{xy(bend)} L{xy(end)}", color, width)


def street(camera: float) -> str:
    # World layers move at different speeds. Street architecture always keeps its orientation.
    out = ['<rect width="360" height="640" fill="url(#sky)"/>']
    for i in range(-2, 4):
        x = i * 167 - camera * 0.08
        y = 91 + (i % 3) * 27
        out.append(
            f'<path transform="translate({x:.2f} {y})" '
            'd="M0 0q6-10 15-6 9-22 25-11 11-3 17 8 13-3 20 9z" fill="#f8f7e4"/>'
        )
    out.append('<path d="M0 237Q62 172 115 215T236 202T361 209V365H0Z" fill="#99bbac"/>')
    for i in range(floor((camera * 0.37 - 150) / 114), floor((camera * 0.37 + 360) / 114) + 1):
        x = i * 114 - camera * 0.37
        h = (8, -8, 13)[i % 3]
        paint = ("#f1cb9e", "#e6ba98", "#f0d6ac")[i % 3]
        roof = ("#a86655", "#698895", "#b17a60")[i % 3]
        out.append(
            f'<g transform="translate({x:.2f} {218 + h})" stroke="#687d79" stroke-width="1.4">'
            f'<path d="M4 14H100V117H4z" fill="{paint}"/>'
            f'<path d="M-4 16 26-15h65l17 31z" fill="{roof}"/>'
            '<path d="M20 28h21v26H20zm39 0h21v26H59z" fill="#83a6a8"/>'
            '<path d="M30 29v23m39-23v23m-48-13h19m20 0h19" stroke="#e9dbb8"/>'
            '<path d="M18 68h25v37H18zm42 3h18v34H60z" fill="#a1b8ac"/></g>'
        )
    out.append(
        '<path d="M0 322Q70 307 133 318T261 313T360 315V390H0z" fill="#93b799"/>'
        '<path d="M0 345h360v54H0z" fill="#8daba3"/><path d="M0 373h360v53H0z" fill="#a3beb0"/>'
    )
    for i in range(floor((camera * 0.68 - 75) / 151), floor((camera * 0.68 + 430) / 151) + 1):
        x = i * 151 - camera * 0.68
        out.append(
            f'<g transform="translate({x:.2f} {299 + (i % 2) * 10})">'
            '<ellipse cy="58" rx="20" ry="4" fill="#7f9e8e"/>'
            '<path d="M-3 58 0 3l5-3 1 58z" fill="#856e57"/>'
            '<path d="M0 18q-25 3-27-16-13-16 2-31-1-18 14-20 15-19 29-5 '
            '18 4 15 20 17 11 9 28-1 20-27 24z" fill="#66998a"/>'
            '<path d="M-23-16q-7-14 7-24 0-10 13-11 16-14 26 0-22-3-19 13-19-5-27 22z" '
            'fill="#8fb599"/><path d="M1 28 3-15m0 23 '
            '12-11" fill="none" stroke="#607f70" stroke-width="2"/></g>'
        )
    out.append(
        '<path d="M0 376h360v264H0z" fill="url(#pavement)"/>'
        '<path d="M0 379h360m-360 8h360" stroke="#c2b5a1" fill="none" stroke-width="2"/>'
        '<path d="M0 505h360M0 600h360" stroke="#d3c5b1" fill="none" stroke-width="1.4"/>'
    )
    for i in range(floor((camera - 340) / 146), floor((camera + 480) / 146) + 1):
        x = i * 146 - camera
        out.append(path(f"M{x + 45:.1f} 387l-39 118 -73 135", "#cfc1ae", 1.6))
    return "".join(out)


def handler(p: Pose, mouth: tuple[float, float, float]) -> str:
    hip, sh, head = p.hip, p.shoulder, p.face
    out = []
    for i, foot in enumerate(p.feet):
        delta = foot - hip
        knee = hip + 0.49 * delta + complex(7 + 19 * p.seated, -7 - 7 * i)
        air_knee = hip + complex(-17 - 6 * i, 19 + 7 * i)
        knee += (air_knee - knee) * p.lift
        if p.fall:
            knee = picture_to_stage((p.fall.body.far_knee, p.fall.body.near_knee)[i], p.camera_x)
        out.append(limb(hip, knee, foot - 4j, ("#60717b", INK)[i], 4.7))
        out.append(path(f"M{xy(foot - 5 - 6j)}q3-2 8 0l8 3q3 1 2 4h-19z", INK, 1.8, "#eddba9"))
    elbow = (sh + p.free_hand) / 2 + complex(-13, 5)
    out.append(limb(sh, elbow, p.free_hand, "#556676", 4.4))
    out.append(ellipse(p.free_hand, 3.8, 4.1, INK))
    out.append(path(f"M{xy(sh - 3)}q6-4 12 1L{xy(hip + 8)}q-7 5-17 1z", INK, 2.5, "#438e97"))
    out.append(path(f"M{xy(sh + 1j)}q6 7 12 1l-3 7-5 1-8 9 2-12z", "#a54e35", 1.1, "#ef7952"))
    grip = picture_to_stage(p.fall.body.grip, p.camera_x) if p.fall else p.lead.hand
    elbow = (sh + grip) / 2 + complex(-5, 14 - 11 * p.lift)
    out.append(limb(sh + 4 + 3j, elbow, grip, INK, 4.8))
    out.append(ellipse(grip, 4.4, 4.2, INK))
    worry = ease(p.t, 43, 54) - ease(p.t, 130, 150)
    blink = min(1.0, min(abs(p.t - f) / 2 for f in (23, 129, 153, 213)))
    tilt = -6 - 15 * p.lift + 11 * p.seated
    head_scale = 1.52 - 0.16 * p.lift if p.fall else 1.0
    out.append(f'<g transform="translate({xy(head)}) rotate({tilt:.1f}) scale({head_scale:.3f})">')
    out.append(
        '<path d="M-21-5q0-19 20-20 20-1 23 18l-1 15q-4 17-21 16-16-1-21-19z" '
        'fill="#fff0d6" stroke="#253645" stroke-width="3"/>'
        '<path d="M-21-8q-1-19 13-23 5-8 11-5 2 2 0 4 14-1 18 16z" '
        'fill="#d58a37" stroke="#253645" stroke-width="2.5"/>'
        '<path d="M-22-11q20-7 37-6l5 4q-16 2-40 '
        '8z" fill="#f6bd5a" stroke="#253645" stroke-width="2"/>'
    )
    for x in (0, 13):
        y = -1 - worry * 2
        if blink < 0.3:
            out.append(path(f"M{x - 3} {y}q3 2 6 0", INK, 1.6))
        else:
            out.append(ellipse(complex(x, y), 4.3, (4.3 + 2 * worry) * blink, "white"))
            out.append(ellipse(complex(x + 1.6, y + 1.0), 1.8, (2.4 + 0.4 * worry) * blink, INK))
        out.append(path(f"M{x - 4} {y - 6.4 - worry * 1.2:.2f}q3 {-2 - worry:.2f} 7 0", INK, 1.7))
    opened, rounded, wide = mouth
    if opened > 0.10 or worry > 0.3:
        out.append(
            ellipse(
                complex(9, 12),
                2.4 + 2.5 * wide + 1.9 * worry,
                1.5 + 4.5 * opened + 2 * worry + rounded,
                INK,
            )
        )
    else:
        out.append(path(f"M4 12q4 {3 - 6 * p.seated:.1f} 9 -1", INK, 1.7))
    out.append("</g>")
    return "".join(out)


def terrier(p: Pose) -> str:
    d = p.dog
    out = []
    for i, leg in enumerate(p.legs):
        color = "#ccac87" if i < 2 else "#fff1d9"
        d_leg = f"M{xy(leg.root)} L{xy(leg.joint)} L{xy(leg.ankle)} L{xy(leg.tip - 1.5j)}"
        out.append(path(d_leg, INK, 5.4))
        out.append(path(d_leg, color, 3.1))
        out.append(ellipse(leg.tip - 1.5j, 3.1, 1.5, INK))
    wag = sin(p.t * 0.37)
    out.append(f'<g transform="translate({xy(d)})">')
    out.append(
        path(
            f"M-16 -3Q-33 {-2 + wag * 4:.2f} -37 {-19 + wag * 4:.2f}q6 2 10 9l13 1z",
            INK,
            1.9,
            "#e7a464",
        )
    )
    out.append(path("M-25-3q0-10 11-13 15-4 27 4l5 8q-2 11-20 12-18 1-23-4z", INK, 2.1, "#fff1da"))
    out.append('<path d="M-20-11q8-9 21-4l-3 8q-4 6-9 2z" fill="#d89a63"/>')
    # The lead clips onto the near side of the collar.
    out.append(path("M12-13l10-4 4 6-11 6z", INK, 1.8, "#287e81"))
    out.append(ellipse(17 - 7j, 2.6, 3.0, "#f1bb53"))
    facing = 1 - 2 * p.look_back
    nod = 4 * sin(p.t * 0.31) * (1 - p.look_back) + 10 * p.look_back
    out.append(f'<g transform="translate(19 -23) rotate({nod:.1f})">')
    out.append(ellipse(-1j, 15.2, 16.0, INK))
    out.append(ellipse(-1j, 13.2, 14.0, "#fff3df"))
    muzzle = complex(12 * facing, 4)
    out.append(ellipse(muzzle, 11.1, 7.1, INK))
    out.append(ellipse(muzzle - 1j, 10.1, 5.9, "#fff3df"))
    ear = 3 * sin(p.t * 0.28)
    out.append(
        path(
            f"M{-5 * facing:.1f} -12q{-14 * facing:.1f} -3 {-16 * facing:.1f} 6"
            f"l{(-2 - ear) * facing:.1f} 8q{9 * facing:.1f} 6 {16 * facing:.1f} -5z",
            INK,
            1.7,
            "#ad744f",
        )
    )
    eye = complex(8 * facing, -5)
    out.append(ellipse(eye, 3.3, 4.0, "white"))
    out.append(ellipse(eye + complex(1.3 * facing, -0.4), 1.9, 2.6, INK))
    out.append(ellipse(complex(20 * facing, 1), 3.6, 2.8, INK))
    out.append(path(f"M{10 * facing:.1f} 5q{4 * facing:.1f} 4 {8 * facing:.1f} 0", INK, 1.5))
    out.append("</g></g>")
    return "".join(out)


def project(p: Pose, action: DogWalk, point: complex) -> complex:
    sign = 1 if action.direction == "right" else -1
    center = p.camera_x if p.fall else p.camera_x - 19 * p.lift
    return complex(180 + sign * (point.real - center) * 1.42, 475 + (point.imag - GROUND) * 1.42)


def artwork(p: Pose, action: DogWalk, width: int, mouth: tuple[float, float, float]) -> str:
    height = width * 16 // 9
    sign = 1 if action.direction == "right" else -1
    center = p.camera_x if p.fall else p.camera_x - 19 * p.lift
    origin = project(p, action, 0j)
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{width}" height="{height}" viewBox="0 0 360 640">',
        '<defs><linearGradient id="sky" x2="0" y2="1" gradientUnits="objectBoundingBox">'
        '<stop stop-color="#70b8c9"/><stop offset=".7" stop-color="#d8e9d8"/></linearGradient>'
        '<linearGradient id="pavement" x2="0" y2="1"><stop stop-color="#dfd4bf"/>'
        '<stop offset="1" stop-color="#f2e8d4"/></linearGradient></defs>',
        street(sign * center * 1.42),
        f'<g transform="translate({xy(origin)}) scale({sign * 1.42} 1.42)" '
        'stroke-linejoin="round" stroke-linecap="round">',
    ]
    floor_y = max(paw.tip.imag for paw in p.paws) if p.fall else GROUND
    out.append(ellipse(complex(p.hip.real + 4, floor_y + 1), 22 - 9 * p.lift, 2.3, "#b2ae9d"))
    out.append(ellipse(complex(p.dog.real, floor_y + 1), 23, 2.0, "#b2ae9d"))
    lead = p.lead
    out.extend((terrier(p), handler(p, mouth)))
    out.append(path(f"M{xy(lead.hand)}Q{xy(lead.control)} {xy(lead.collar)}", LEAD_COLOR, 2.7))
    if p.fall and (p.fall.slack > 0.5 or p.fall.release > 0.5):
        out.append(path(f"M{xy(lead.hand)}q-10 -5 -12 1t12 -1", LEAD_COLOR, 2.7))
    else:
        out.append(ellipse(lead.hand, 3.9, 3.6, INK))
    out.append(ellipse(lead.collar, 2.7, 2.7, INK))
    out.append(ellipse(lead.collar, 1.5, 1.5, "#eeb665"))
    if action.contact_overlay:
        for pt in (lead.hand, lead.collar, *(paw.tip for paw in p.paws if paw.planted)):
            out.append(
                f'<circle cx="{pt.real:.3f}" cy="{pt.imag:.3f}" '
                f'r="5.5" fill="none" stroke="#ab28cb" stroke-width="1.4"/>'
            )
    out.append("</g></svg>")
    return "".join(out)
