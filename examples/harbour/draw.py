"""Draw the harbour scene into the frame directory prepared by render.py."""

import json
import sys
from itertools import pairwise
from math import cos, hypot, pi, sin, sqrt
from pathlib import Path

import cairo

cues = []
W, H = 1280, 720
INK = "#243941"
SKIN = "#f7b984"
TEAL = "#247e80"
CREAM = "#fff0d0"
SHIRT = "#ef7948"
BOOT = "#704331"
surf = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
c = cairo.Context(surf)


def col(color):
    if isinstance(color, tuple):
        c.set_source_rgba(*color)
        return
    c.set_source_rgb(*(int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)))


def paint(fill=None, edge=None, w=2):
    if fill:
        col(fill)
        c.fill_preserve()
    if edge:
        col(edge)
        c.set_line_width(w)
        c.stroke_preserve()
    c.new_path()


def rect(x, y, w, h, fill):
    c.rectangle(x, y, w, h)
    paint(fill)


def rounded(x, y, w, h, r, fill, edge=None, lw=2):
    r = min(r, w / 2, h / 2)
    c.new_sub_path()
    for a, b, i in [
        (x + w - r, y + r, -1),
        (x + w - r, y + h - r, 0),
        (x + r, y + h - r, 1),
        (x + r, y + r, 2),
    ]:
        c.arc(a, b, r, i * pi / 2, (i + 1) * pi / 2)
    c.close_path()
    paint(fill, edge, lw)


def poly(pts, f, edge=None, w=2):
    c.move_to(*pts[0])
    for p in pts[1:]:
        c.line_to(*p)
    c.close_path()
    paint(f, edge, w)


def path(ops, fill=None, edge=None, w=2):
    for op, *v in ops:
        {"M": c.move_to, "L": c.line_to, "C": c.curve_to, "Z": c.close_path}[op](*v)
    paint(fill, edge, w)


def line(points, color=INK, w=2):
    c.move_to(*points[0])
    for p in points[1:]:
        c.line_to(*p)
    paint(None, color, w)


def ell(x, y, rx, ry, fill, edge=None, w=2):
    c.save()
    c.translate(x, y)
    c.scale(rx, ry)
    c.arc(0, 0, 1, 0, 2 * pi)
    c.restore()
    paint(fill, edge, w)


def text(x, y, s, size, color=INK, bold=True):
    c.select_font_face(
        "DejaVu Sans",
        cairo.FONT_SLANT_NORMAL,
        cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL,
    )
    c.set_font_size(size)
    col(color)
    c.move_to(x, y)
    c.show_text(s)
    c.new_path()


def clamp(x):
    return max(0, min(1, x))


def sm(x):
    x = clamp(x)
    return x * x * (3 - 2 * x)


def f(t, a, b):
    return sm((t - a) / (b - a))


def mix(a, b, t):
    return a + (b - a) * t


def vec(a, b, u):
    return tuple(mix(x, y, u) for x, y in zip(a, b, strict=True))


def distprog(t, a, b, r=0.5):
    t = max(0, min(b - a, t - a))
    T = b - a
    if t < r:
        v = t * t / (2 * r)
    elif t > T - r:
        v = T - r - (T - t) ** 2 / (2 * r)
    else:
        v = t - r / 2
    return v / (T - r)


def ground_scene(t, cam):
    # Distant island, striped lighthouse and sailing boats.
    rect(-1900, -900, 6100, 1150, "#bce4df")
    ell(120 + 0.76 * cam, 86, 36, 36, "#ffdc91")
    for i in range(8):
        x = -200 + i * 380 + 0.57 * cam + 9 * sin(0.035 * t + i)
        path(
            [
                ("M", x, 89),
                ("C", x + 6, 76, x + 25, 77, x + 30, 80),
                ("C", x + 33, 59, x + 68, 62, x + 71, 80),
                ("C", x + 89, 73, x + 103, 81, x + 104, 89),
                ("Z",),
            ],
            "#ebf1dc",
        )
    rect(-1900, 238, 6100, 98, "#83c8c4")
    for i in range(12):
        x = -60 + i * 238 + 0.53 * cam
        path(
            [
                ("M", x - 140, 238),
                ("C", x - 69, 223, x - 29, 167, x + 26, 195),
                ("C", x + 54, 208, x + 78, 221, x + 126, 238),
                ("Z",),
            ],
            "#8bb4aa",
        )
    for i in range(60):
        x = (i * 89) % 2740 - 110 + 0.43 * cam
        y = 254 + (i * 31) % 57
        line([(x, y), (x + 14 + i % 27, y)], "#a7d8cc", 1.7)
    for start in [74, 915, 1720]:
        x = start + 0.45 * cam
        poly([(x - 10, 239), (x - 6, 187), (x + 6, 187), (x + 10, 239)], "#f5e2bc")
        poly([(x - 8, 215), (x - 7, 204), (x + 7, 204), (x + 8, 215)], "#cc775e")
        rect(x - 7, 180, 14, 9, "#3c6971")
        poly([(x - 12, 180), (x, 172), (x + 12, 180)], "#ae6c57")
    for i in range(4):
        x = 345 + i * 480 + 0.47 * cam + t * 0.9
        poly([(x, 269), (x + 27, 269), (x + 22, 275), (x + 5, 275)], "#598f92")
        poly([(x + 13, 247), (x + 13, 267), (x + 2, 267)], "#fbebca")
        poly([(x + 16, 250), (x + 23, 267), (x + 16, 267)], "#de9274")
    for i in range(7):
        x = 75 + i * 205 + 0.56 * cam + 4 * t
        y = 130 + (i * 37) % 60
        path(
            [
                ("M", x - 5, y - 2),
                ("C", x - 3, y - 4, x - 1, y - 2, x, y),
                ("C", x + 2, y - 3, x + 4, y - 4, x + 6, y - 3),
            ],
            None,
            "#6e9090",
            1.5,
        )
    # Harbour railing and concrete promenade.
    rect(-1900, 325, 6100, 250, "#e6c79a")
    rect(-1900, 332, 6100, 6, "#d6af80")
    rect(-1900, 353, 6100, 3, "#ecd5ab")
    for i in range(-10, 28):
        x = i * 102
        rounded(x, 284, 8, 46, 3, "#6f9691")
    rect(-1900, 287, 6100, 5, "#739b94")
    rect(-1900, 307, 6100, 3, "#8baa9b")
    rect(-1900, 397, 6100, 160, "#efd8ae")
    rect(-1900, 461, 6100, 7, "#d4b88d")
    for i in range(-25, 60):
        x = i * 66
        line([(x, 464), (x - 7, 478)], "#d5b88f", 1.7)
    for i in range(85):
        x = (i * 89) % 2840 - 140
        y = 412 + (i * 37) % 43
        line([(x, y), (x + 5 + (i % 3) * 4, y)], "#dcc198", 1.2)
    # Stop furniture establishes the ground as Milo travels.
    for x in [64, 1320]:
        rounded(x - 3, 196, 7, 191, 3, "#47696a")
        rounded(x - 25, 158, 51, 47, 8, "#236b71", INK, 2)
        rounded(x - 14, 168, 29, 18, 4, "#f7e5b7")
        rect(x - 12, 171, 25, 6, "#38787b")
        for k in [-8, 8]:
            ell(x + k, 188, 3, 3, "#f7e5b7")
    for x in [260, 1575]:
        for q in [0, 97]:
            line([(x + q, 361), (x + q - 3, 384)], "#51635a", 5)
        for y in [334, 345, 357]:
            rounded(x - 11, y, 120, 8, 3, "#b97c52", "#765b46", 1.2)


def bag(x, y, ang=0):
    c.save()
    c.translate(x, y)
    c.rotate(ang)
    rounded(-9, 1, 18, 14, 5, None, INK, 4)
    rounded(-20, 11, 40, 28, 6, "#db5947", INK, 2.8)
    rounded(-20, 10, 40, 7, 3, "#f38659", INK, 2)
    rounded(-3, 14, 6, 6, 1.7, "#ffdc94", INK, 1)
    line([(-15, 34), (-8, 34)], "#f78a61", 1.8)
    c.restore()


def palm(x, y, angle=0, openhand=False, scale=1):
    c.save()
    c.translate(x, y)
    c.rotate(angle)
    c.scale(scale, scale)
    if openhand:
        path(
            [
                ("M", -6, 4),
                ("C", -9, 1, -12, -4, -10, -6),
                ("C", -8, -8, -6, -3, -4, -2),
                ("L", -5, -12),
                ("C", -5, -16, -1, -16, 0, -12),
                ("L", 1, -5),
                ("L", 2, -15),
                ("C", 3, -18, 6, -17, 6, -13),
                ("L", 6, -5),
                ("L", 9, -11),
                ("C", 11, -14, 14, -12, 13, -9),
                ("L", 10, 0),
                ("C", 10, 9, 0, 13, -6, 4),
                ("Z",),
            ],
            SKIN,
            INK,
            2.2,
        )
    else:
        ell(0, 0, 7.4, 7.8, SKIN, INK, 2.3)
    c.restore()


def arm(a, b, d, back=False):
    stroke = "#375051" if back else INK
    for w, color in [(13.5, stroke), (8.7, "#d89468" if back else SKIN)]:
        line([a, b, d], color, w)
    mid = vec(a, b, 0.53)
    line([a, mid], stroke, 16)
    line([a, mid], "#cc6544" if back else SHIRT, 11)


def max_head(t, x, y):
    c.save()
    c.translate(x, y)
    ell(-2, 1, 24, 27, "#a7c98e", INK, 2.5)
    ell(18, 5, 6, 8, "#abc990", INK, 2)
    for a in [-12, -2, 8]:
        path(
            [
                ("M", a - 4, -20),
                ("C", a - 12, -39, a + 4, -35, a + 10, -23),
                ("L", a + 7, -18),
                ("Z",),
            ],
            "#674d42",
            INK,
            1.4,
        )
    for a in [-14, 1]:
        ell(a, -2, 6.1, 8, "#fff3d8", INK, 1.4)
        ell(a - 2.8, -1, 2.8, 4.6, INK)
    line([(-20, -13), (-12, -16)], INK, 2.2)
    line([(-3, -15), (5, -13)], INK, 2.2)
    path([("M", -12, 10), ("C", -6, 15, 0, 16, 5, 11)], None, INK, 1.8)
    c.restore()


def bus(t, x, drive):
    c.save()
    c.translate(x, 0)
    ell(206, 386, 211, 10, "#b49c79")
    for wx in [63, 347]:
        ell(wx, 355, 29, 30, INK)
        ell(wx, 355, 16, 16, "#aac2ac", INK, 3)
        ell(wx, 355, 7, 7, "#537977")
        for i in range(3):
            aa = i * 2 * pi / 3 + drive / 29
            ell(wx + 10 * cos(aa), 355 + 10 * sin(aa), 2, 2, "#dbe0bf")
    rounded(0, 181, 419, 171, 19, "#e9c67d", INK, 3.3)
    rounded(0, 197, 419, 100, 12, "#ecdfaf", INK, 2.1)
    rounded(0, 282, 419, 68, 12, "#337f80", INK, 2.7)
    rect(2, 288, 415, 7, "#e6aa61")
    for wx in [10, 89, 168, 247, 326]:
        rounded(wx, 204, 71, 71, 6, "#639a9b", INK, 2.7)
        rounded(wx + 4, 208, 63, 63, 3, "#85b5ac")
        poly([(wx + 9, 264), (wx + 39, 212), (wx + 49, 212), (wx + 19, 264)], "#a1c6b6")
    rounded(243, 183, 86, 15, 3, "#2e555a")
    text(251, 194, "HARBOUR", 10, "#ffe4a7")
    for a in [112, 120, 128]:
        rounded(a, 322, 39, 2, 1, "#286466")
    for j in range(3):
        path(
            [("M", 205 + j * 9, 324), ("C", 209 + j * 9, 318, 213 + j * 9, 318, 216 + j * 9, 321)],
            None,
            "#fae5ae",
            2.6,
        )
    rounded(-3, 334, 18, 7, 3, "#304f54")
    rounded(403, 330, 17, 7, 3, "#f4c57d", INK, 1.5)
    rounded(6, 300, 7, 12, 3, "#cc7252", INK, 1.4)
    # Open rear window with Max visible.
    rounded(10, 204, 71, 71, 6, "#385e63", INK, 2.5)
    c.save()
    c.rectangle(10, 203, 71, 71)
    c.clip()
    ell(47, 282, 28, 27, "#efb94d", INK, 2)
    max_head(t, 45 + 2 * sin(t * 2), 242 + 1.5 * cos(t * 2.3))
    c.restore()
    rounded(9, 271, 74, 6, 2, "#f1dcac", INK, 1.4)
    hand = f(t, 12.3, 13.7)
    end = (
        mix(19, -4, hand) + 20 * f(t, 14.05, 14.74),
        mix(269, 286, hand) - 25 * f(t, 14.05, 14.74),
    )
    line([(42, 263), (28, 278), end], INK, 9)
    line([(42, 263), (28, 278), end], "#a7c98e", 6)
    ell(*end, 5.3, 5.3, "#a7c98e", INK, 1.7)
    c.restore()


def leg(hip, foot, back=False, angle=0):
    dx, dy = foot[0] - hip[0], foot[1] - hip[1]
    length = max(1, hypot(dx, dy))
    reach = 43
    h = sqrt(max(0, reach * reach - length * length / 4))
    k = ((hip[0] + foot[0]) / 2 + dy / length * h, (hip[1] + foot[1]) / 2 - dx / length * h)
    for w, co in [(15, INK), (10, "#45625f" if back else "#506e6d")]:
        line([hip, k, foot], co, w)
    c.save()
    c.translate(*foot)
    c.rotate(angle)
    x = y = 0
    path(
        [
            ("M", x - 7, y - 3),
            ("C", x - 3, y - 5, x + 2, y - 5, x + 6, y - 1),
            ("L", x + 16, y + 2),
            ("C", x + 24, y + 6, x + 18, y + 9, x + 12, y + 9),
            ("L", x - 7, y + 9),
            ("C", x - 12, y + 7, x - 11, y + 1, x - 7, y - 3),
            ("Z",),
        ],
        "#925d44" if back else BOOT,
        INK,
        2.8,
    )
    line([(x - 7, y + 7), (x + 15, y + 7)], "#f1d194", 2.6)
    c.restore()


def ease5(x):
    x = clamp(x)
    return x * x * x * (10 + x * (-15 + 6 * x))


def gate(t, a, b):
    return ease5((t - a) / (b - a))


def rootx(t):
    return 182 + 264 * distprog(t, 2, 5.75, 0.38) + 715 * distprog(t, 9.14, 13.70, 0.54)


bouts = [(2, 5.75, 8, 0.58, 17), (9.14, 13.7, 13, 0.32, 42)]


def footprints(side):
    events = []
    for a, b, count, stance, height in bouts:
        half = (b - a) / (count + 1)
        cycle = 2 * half
        sidebeat = 0 if side else 1
        times = [a + half * (i + 1) for i in range(count) if i % 2 == sidebeat]
        rest = 10 if not side else -12
        leave = a + half * (0.21 if side else 1.06)
        events.append((a - 1, leave, rootx(a) + rest, height))
        for land in times:
            off = land + stance * cycle
            wx = rootx((land + off) * 0.5)
            events.append((land, off, wx, height))
        # Land each shoe independently, then keep it at its final mark.
        prev = events[-1]
        landing = b - (0.05 if side else 0.00)
        if prev[1] + 0.13 > b:
            landing = events.pop()[0]
        events.append((landing, b + 0.98, rootx(b) + rest, height))
    return events


steps = [footprints(False), footprints(True)]


def run_height_keys():
    start, end, *_ = bouts[1]
    contacts = sorted(
        (max(land, start), min(off, end))
        for sequence in steps
        for land, off, _, _ in sequence
        if land < end and off > start
    )
    # Overlapping left/right stances are one period of support. Only a real
    # gap between them can carry the body through a flight apex.
    support = []
    for land, off in contacts:
        if support and land <= support[-1][1]:
            support[-1] = (support[-1][0], max(off, support[-1][1]))
        else:
            support.append((land, off))
    keys = [(start, 0.0)]
    for i, (land, off) in enumerate(support):
        if i:
            keys.append(((support[i - 1][1] + land) / 2, -8.0))
        keys.append(((land + off) / 2, 6.0))
    return [*keys, (end, 0.0)]


run_heights = run_height_keys()


def run_bounce(t):
    for (start, low), (end, high) in pairwise(run_heights):
        if start <= t <= end:
            return mix(low, high, sm((t - start) / (end - start)))
    return 0.0


def feet(t, side):
    seq = steps[side]
    last = seq[0]
    for e in seq:
        if t < e[0]:
            if t <= last[1] or last[2] == e[2]:
                return last[2], -9, 0, True
            u = clamp((t - last[1]) / (e[0] - last[1]))
            v = ease5(u)
            a = sin(pi * u) ** 2
            h = e[3] * min(1, abs(e[2] - last[2]) / 47)
            # Heel tucks during recovery; toe opens for the landing.
            return (
                mix(last[2], e[2], v) - 0.28 * h * a * (1 - u),
                -9 - h * a * (1.24 - 0.48 * u),
                0.58 * a * (1 - 1.55 * u),
                False,
            )
        last = e
    return last[2], -9, 0, True


def ik(a, end, l1, l2, sign=1):
    dx, dy = end[0] - a[0], end[1] - a[1]
    d = max(0.0001, hypot(dx, dy))
    proj = (d * d + l1 * l1 - l2 * l2) / (2 * d)
    h = sqrt(max(0, l1 * l1 - proj * proj))
    return a[0] + (proj * dx + sign * h * dy) / d, a[1] + (proj * dy - sign * h * dx) / d


def limb(a, length, angle):
    return a[0] + length * sin(angle), a[1] + length * cos(angle)


def handdraw(pt, ang, spread):
    c.save()
    c.translate(*pt)
    c.rotate(ang)
    # Continuous finger curl makes the silhouette open over several frames.
    for layer in [0, 1]:
        thick = 6.4 if layer == 0 else 3.6
        co = INK if layer == 0 else SKIN
        for bx, ln, fan in [(-4.6, 11, -0.29), (-1.4, 15, -0.08), (2, 14, 0.13), (5.1, 10, 0.35)]:
            ext = 3 + spread * ln
            line([(bx, -1), (bx + fan * spread * ln, -1 - ext)], co, thick)
        line([(-4, 1), (-6 - 4.4 * spread, -0.8 - 3 * spread)], co, thick)
        ell(0, 2, 7.4 - layer * 1.25, 7.3 - layer * 1.25, co)
    c.restore()


def getpose(t):
    x = rootx(t)
    walk = gate(t, 1.98, 2.4) * (1 - gate(t, 5.38, 5.82))
    run = gate(t, 8.99, 9.75) * (1 - gate(t, 13.22, 13.80))
    phW = (t - 2) / ((5.75 - 2) / 9 * 2)
    phR = (t - 9.14) / ((13.7 - 9.14) / 14 * 2)
    # The torso compresses after contact and rises through toe-off.
    push = run * run_bounce(t) + 2.2 * walk * cos(4 * pi * phW - 0.9)
    anticip = gate(t, 8.77, 9.06) * (1 - gate(t, 9.06, 9.58))
    settle = gate(t, 13.24, 13.6) * (1 - gate(t, 13.64, 14.12))
    give = gate(t, 13.03, 14.05)
    w = gate(t, 0.01, 0.67) * (1 - gate(t, 1.57, 2.35))
    sp = gate(t, 5.72, 6.35) * (1 - gate(t, 8.46, 9.09))
    lean = 5 * walk + 16 * run + 3.5 * give + 9 * anticip - 5 * settle
    ankles = [feet(t, side) for side in (0, 1)]
    desired = -87 + push + 6 * run + 6 * anticip + 4 * settle
    # Keep a small bend through extension. Smoothly lift or lower the hips with both legs.
    hipy = desired
    for i, (ax, ay, _, __) in enumerate(ankles):
        dx = ax - x - (4 if i == 0 else -4)
        lo = ay - sqrt(max(1, 83**2 - dx * dx))
        hipy = 0.5 * (hipy + lo + sqrt((hipy - lo) ** 2 + 1.4**2))
    hip = (0, hipy)
    sh = (1 + lean, hipy - 46)
    # The elbow leads the wave; the wrist and fingertips lag the reversal.
    swingW = cos(2 * pi * phW + 0.08)
    swingR = cos(2 * pi * phR + 0.12)
    a = -0.16 - 0.48 * walk * swingW - 1.03 * run * swingR
    b = (
        0.22
        - 0.51 * walk * cos(2 * pi * phW - 0.26)
        - run * (1.03 * cos(2 * pi * phR - 0.34) - 0.97)
    )
    waveangle = 2 * pi * (1.9 * t - 0.22)
    a = mix(a, -1.79 + 0.095 * sin(waveangle + 0.55), w)
    b = mix(b, -3.06 + 0.39 * sin(waveangle), w)
    a = mix(a, 0.18, sp * 0.8)
    b = mix(b, 1.72, sp * 0.85)
    E = limb(sh, 29, a)
    H = limb(E, 33, b)
    palmang = mix(0.13 * sin(2 * pi * phR) * run, -0.09 + 0.46 * sin(waveangle - 0.32), w)
    farA = +0.10 + 0.49 * walk * swingW + 0.69 * run * swingR
    farB = (
        -0.15
        + 0.4 * walk * cos(2 * pi * phW - 0.2)
        + run * (0.92 + 0.56 * cos(2 * pi * phR - 0.32))
    )
    farE = limb(sh, 28, farA)
    farH = limb(farE, 32, farB)
    farH = vec(farH, (sh[0] + 33, sh[1] + 10), sp)
    farH = vec(farH, (34, -127), give)
    farH = vec(farH, (sh[0] + 4, sh[1] + 50), gate(t, 14.05, 14.78))
    farE = ik(sh, farH, 29, 32, -1)
    return {
        "ankles": ankles,
        "sh": sh,
        "hip": hip,
        "w": w,
        "sp": sp,
        "farH": farH,
        "farE": farE,
        "H": H,
        "E": E,
        "palmang": palmang,
        "phR": phR,
        "give": give,
    }


def milo(t, x, walk, run):
    p = getpose(t)
    sh = p["sh"]
    hip = p["hip"]
    w = p["w"]
    speak = p["sp"]
    c.save()
    c.translate(x, 413)
    air = clamp(min(-ft[1] - 9 for ft in p["ankles"]) / 12)
    ell(0, 0, 32 - 6 * air, 5.5 - 1.2 * air, "#c6ad83")
    for i in (1, 0):
        fx, fy, angle, _ = p["ankles"][i]
        leg((4 if i == 0 else -4, hip[1]), (fx - x, fy), i == 1, angle)
    farH = p["farH"]
    arm(sh, p["farE"], farH, True)
    if t < 14.05:
        bag(*farH, 0.12 * run * sin(2 * pi * p["phR"] - 0.7) * (1 - p["give"]) - 0.12 * speak)
    palm(*farH, scale=0.85)
    # Tapered jacket and small fabric details.
    path(
        [
            ("M", sh[0] - 11, sh[1] - 5),
            ("C", sh[0] - 22, sh[1] + 6, -15, hip[1] - 10, -16, hip[1] + 1),
            ("C", -6, hip[1] + 7, 8, hip[1] + 7, 16, hip[1] + 1),
            ("L", sh[0] + 14, sh[1] + 6),
            ("C", sh[0] + 12, sh[1] - 2, sh[0] + 5, sh[1] - 6, sh[0] - 11, sh[1] - 5),
            ("Z",),
        ],
        SHIRT,
        INK,
        3,
    )
    line([(sh[0] + 4, sh[1] + 1), (5, hip[1] + 1)], "#ad573d", 1.6)
    for j in range(2):
        ell(sh[0] + 3 - j * 2, sh[1] + 13 + 11 * j, 1.7, 1.7, "#ffe3a6")
    head = (sh[0] + 4, sh[1] - 34)
    c.save()
    c.translate(*head)
    c.rotate(0.04 * walk + 0.11 * run - 0.035 * w + 0.04 * speak * sin(t * 6))
    ell(0, 0, 27, 30, SKIN, INK, 2.7)
    ell(-24, 4, 6.3, 8, "#eca574", INK, 1.9)
    path([("M", 19, -2), ("C", 32, -1, 34, 7, 26, 8), ("L", 22, 8)], SKIN, INK, 2)
    blink = min(1, min(abs(t - a) for a in [0.9, 3.9, 6.0, 8.86, 12.14, 14.5]) / 0.09)
    for ex in [2, 17]:
        if blink < 0.18:
            line([(ex - 5, -5), (ex + 4, -5)], INK, 2)
        else:
            ell(ex, -5, 5.6, 7.2 * blink, "#fff6df", INK, 1.3)
            ell(ex + 2.3, -4.8, 2.35, 4.2 * blink, INK)
    line([(-4, -16), (5, -17 - 2 * run)], INK, 2.2)
    line([(12, -17), (19, -15)], INK, 2.1)
    ci = min(len(cues) - 1, int(t * 24))
    cn = min(ci + 1, len(cues) - 1)
    o, rr, ww = (mix(a, b, t * 24 - ci) for a, b in zip(cues[ci], cues[cn], strict=True))
    if o > 0.035:
        ell(13, 15, 4.5 + 3 * ww - 1.4 * rr, 2 + 5.8 * o, "#683c3c", INK, 1.5)
    else:
        path([("M", 6, 14), ("C", 10, 18 - w * 2, 15, 19, 19, 13)], None, INK, 1.9)
    path(
        [
            ("M", -28, -16),
            ("C", -28, -39, -5, -46, 11, -34),
            ("C", 19, -32, 21, -26, 23, -21),
            ("L", -24, -11),
            ("Z",),
        ],
        TEAL,
        INK,
        2.7,
    )
    path(
        [
            ("M", -25, -16),
            ("C", -8, -21, 13, -24, 28, -23),
            ("C", 42, -23, 40, -18, 27, -15),
            ("L", -23, -10),
            ("Z",),
        ],
        "#469b91",
        INK,
        2.4,
    )
    line([(-14, -33), (-10, -34)], "#9ac7af", 2.6)
    c.restore()
    nearH = p["H"]
    arm(sh, p["E"], nearH)
    handdraw(nearH, p["palmang"], max(w, 0.62 * speak))
    c.restore()


def render(n):
    t = n / 60
    wd = 264 * distprog(t, 2, 5.75, 0.38)
    rd = 715 * distprog(t, 9.14, 13.70, 0.54)
    x = 182 + wd + rd
    busdr = 644 * distprog(t, 8.53, 13.27, 0.68)
    walk = f(t, 2, 2.22) * (1 - f(t, 5.48, 5.75))
    run = f(t, 9.14, 9.36) * (1 - f(t, 13.41, 13.7))
    # Wides keep the feet visible; the dialogue cut brings the mouth into view.
    if 6 <= t < 8.95:
        z = 2.10
        cx = 307
        cy = 138
    else:
        z = 1.08
        cx = 18 + 0.27 * wd + max(0, rd - 36) * 0.84
        cy = 11
    c.save()
    c.scale(W / 960, H / 540)
    c.set_line_join(cairo.LINE_JOIN_ROUND)
    c.set_line_cap(cairo.LINE_CAP_ROUND)
    c.save()
    c.scale(z, z)
    c.translate(-cx, -cy)
    ground_scene(t, cx)
    bus(t, 555 + busdr, busdr)
    milo(t, x, walk, run)
    if t >= 14.05:
        handx = 555 + busdr - 4 + 20 * f(t, 14.05, 14.74)
        handy = 286 - 25 * f(t, 14.05, 14.74)
        bag(handx, handy)
        ell(handx, handy, 5.3, 5.3, "#a7c98e", INK, 1.7)
    c.restore()
    title = "Hand wave" if t < 2 else "Walk" if t < 6 else "Speak" if t < 8.95 else "Run"
    text(35, 52, title, 28, "#263f49")
    rect(35, 63, 34, 4, "#db7650")
    if 6.25 <= t < 8.65:
        rounded(270, 462, 420, 43, 20, "#fff2d5", INK, 1.8)
        text(293, 491, "“Max! You forgot your lunch!”", 21, INK)
    c.restore()
    surf.flush()


if __name__ == "__main__":
    work = Path(sys.argv[1])
    cues = json.loads((work / "mouth.json").read_text())
    strikes = sorted(
        (step[0], step[3] > 30)
        for sequence in steps
        for previous, step in pairwise(sequence)
        if abs(previous[2] - step[2]) > 1
    )
    (work / "strikes.json").write_text(json.dumps(strikes))
    for frame in range(900):
        render(frame)
        surf.write_to_png(str(work / f"frame-{frame:04d}.png"))
