"""Retarget AnimaLite's DogWalk performance to the opening drawing of He Tried to Walk the Dog.

Input is one 144 x 256 BGR image. All landmark coordinates refer to that drawing.
"""

from math import cos, pi, sin

import cv2 as cv
import numpy as np
from scipy.spatial import Delaunay
from street import Panorama

from animalite.dog_walk import DogWalk, pose

S = 3
W, H = 144 * S, 256 * S
cv.setNumThreads(1)


def v(x, y):
    return np.array((x, y), dtype=float)


def ease(t, a, b):
    u = np.clip((t - a) / (b - a), 0, 1)
    return u * u * (3 - 2 * u)


def blend(a, b, t):
    return a + (b - a) * t


def rotate(angle):
    return np.array(((cos(angle), -sin(angle)), (sin(angle), cos(angle))))


def device(pts):
    return np.rint(np.asarray(pts) * S).astype(np.int32)


def stroke(canvas, pts, ink, width):
    cv.polylines(canvas, [device(pts)], False, ink, max(1, round(width * S)), cv.LINE_AA)


def curve(canvas, a, b, c, ink, width):
    u = np.linspace(0, 1, 28)[:, None]
    stroke(canvas, (1 - u) ** 2 * a + 2 * u * (1 - u) * b + u * u * c, ink, width)


def solid(canvas, shape, color):
    cv.fillPoly(canvas, [device(shape)], color, cv.LINE_AA)


def ellipse(canvas, center, radii, ink, angle=0):
    cv.ellipse(
        canvas,
        tuple(device(center)),
        tuple(np.maximum(device(radii), 1)),
        angle,
        0,
        360,
        ink,
        -1,
        cv.LINE_AA,
    )


def sprite(image, mask):
    return np.dstack((image.astype(float) * (mask[:, :, None] / 255), mask)).round().astype("uint8")


def paste(canvas, tile):
    alpha = tile[:, :, 3, None].astype(np.uint16)
    canvas[:] = (
        tile[:, :, :3].astype(np.uint16) + (canvas.astype(np.uint16) * (255 - alpha) + 127) // 255
    )


def place(canvas, art, center, target, angle=0, scale=1):
    linear = rotate(angle) * scale
    transform = np.c_[linear, (target - linear @ center) * S]
    x, y, w, h = cv.boundingRect(art[:, :, 3])
    corners = (
        np.array(((x, y), (x + w, y), (x + w, y + h), (x, y + h))) @ linear.T + transform[:, 2]
    )
    lo = np.maximum((0, 0), np.floor(corners.min(axis=0) - 1).astype(int))
    hi = np.minimum((W, H), np.ceil(corners.max(axis=0) + 2).astype(int))
    if np.any(hi <= lo):
        return
    transform[:, 2] -= lo
    tile = cv.warpAffine(art, transform, tuple(hi - lo), flags=cv.INTER_LINEAR)
    paste(canvas[lo[1] : hi[1], lo[0] : hi[0]], tile)


def disk(n):
    return cv.getStructuringElement(cv.MORPH_ELLIPSE, (2 * n + 1, 2 * n + 1))


def cut(image, polygon, border=1.5):
    mask = np.zeros((H, W), np.uint8)
    solid(mask, polygon, 255)
    radius = round(border * S)
    labels = np.full((H, W), cv.GC_BGD, np.uint8)
    labels[cv.dilate(mask, disk(radius)) > 0] = cv.GC_PR_BGD
    labels[mask > 120] = cv.GC_PR_FGD
    labels[cv.erode(mask, disk(radius)) > 230] = cv.GC_FGD
    cv.grabCut(image, labels, None, np.zeros((1, 65)), np.zeros((1, 65)), 4, cv.GC_INIT_WITH_MASK)
    return cv.GaussianBlur(((labels & 1) * 255).astype("uint8"), (3, 3), 0.64)


FACE = [
    (35.6, 94),
    (36.2, 86),
    (39.4, 79.2),
    (44.5, 74.8),
    (50.7, 72.5),
    (58.2, 71.5),
    (65.7, 72.5),
    (72.2, 75.7),
    (77.3, 80.8),
    (80.2, 87.3),
    (81, 94.8),
    (80.1, 101),
    (76.2, 108.3),
    (70.2, 113.6),
    (63.5, 116.4),
    (55.7, 117.3),
    (48.7, 115.8),
    (42.8, 111.6),
    (38.2, 105.7),
]
DOG = [
    (63.4, 182.6),
    (64.2, 177),
    (65.7, 175.7),
    (66.8, 177.5),
    (67.6, 183.3),
    (70.1, 187.3),
    (73.3, 189.3),
    (76.3, 187.9),
    (81.9, 187.0),
    (85.8, 184.7),
    (82.2, 184.1),
    (80.2, 181.6),
    (80.4, 177.8),
    (82.4, 173.4),
    (84, 169.2),
    (86.3, 166.2),
    (89.1, 164.7),
    (92.4, 165.2),
    (96.5, 163.2),
    (100, 162.8),
    (102.5, 160.3),
    (103.7, 162),
    (106.7, 162.4),
    (107.5, 164.1),
    (111.5, 165),
    (114.8, 168.2),
    (117, 172.9),
    (117.6, 177.1),
    (119.5, 181.2),
    (119.1, 185.7),
    (116.7, 189.3),
    (111.1, 191.6),
    (107.1, 192.2),
    (105.8, 196.8),
    (104.6, 204.4),
    (104.4, 209.3),
    (102.4, 213.5),
    (99.9, 213.4),
    (98.6, 207.6),
    (96, 207.7),
    (94.2, 207.5),
    (93.3, 213.8),
    (91.7, 216),
    (89.9, 215.6),
    (88.3, 213),
    (88, 208),
    (85.7, 207.2),
    (84.9, 210),
    (82.8, 211.7),
    (80.8, 210),
    (80.5, 206.3),
    (77.3, 205.2),
    (76.1, 211.5),
    (74.4, 214.4),
    (72.1, 213.6),
    (70.5, 209.7),
    (70.4, 202.5),
    (70.5, 196.5),
    (71.4, 193.4),
    (69, 192.3),
    (66.1, 190.7),
]
NECK = v(49.2, 116)
HIP = v(40.5, 155.5)
CENTER = v(58.2, 94.4)
GRIP = v(71.6, 156.4)
FREE = v(59, 153.6)
DOG_CENTER = v(90, 194)
LATCH = v(87.6, 185.6)
FEET = [v(35.2, 210.8), v(50.5, 207.2)]
SHOES = [
    [
        (34.1, 209.0),
        (37.8, 208.5),
        (42.1, 208.6),
        (45.7, 210.2),
        (48.7, 212.4),
        (48.2, 214.1),
        (41.4, 214.1),
        (34.3, 212.9),
    ],
    [
        (49.4, 205.8),
        (54.9, 204.2),
        (59.9, 204.5),
        (63.9, 207.1),
        (64.6, 209.1),
        (62, 210),
        (49.6, 209.8),
    ],
]
HANDS = [
    [
        (54.8, 150.9),
        (56.6, 149.3),
        (61, 149.2),
        (64.1, 150.9),
        (64.8, 153.1),
        (62.5, 154.6),
        (64, 156.7),
        (59.3, 157.8),
        (55.2, 156.6),
        (54, 154.7),
    ],
    [
        (67.7, 154.1),
        (69.5, 151.9),
        (72.7, 152),
        (75, 154.8),
        (75.6, 158.9),
        (73.3, 161.5),
        (70.8, 160.6),
        (68.8, 158.2),
    ],
]
ARM0 = [(49.2, 116), (45.5, 122.5), (42.6, 130), (37.2, 141.5), (41.5, 145), (59, 153.6)]
ARM1 = [(49.2, 116), (52.1, 125.7), (57, 139.8), (71.6, 156.4)]
LEG0 = [(40.5, 155.5), (40.4, 165), (39.1, 183.2), (35.2, 210.8)]
LEG1 = [(40.5, 155.5), (45.1, 166.2), (50.3, 178.5), (50.5, 207.2)]
HANDLE = [
    (60, 153.4),
    (55.8, 153),
    (51.6, 157),
    (47.8, 164.3),
    (44.2, 176.2),
    (41.5, 189.5),
    (41.8, 193.2),
    (43.1, 195.2),
    (46.4, 194.6),
    (49.0, 190.2),
    (49.4, 182.2),
    (47.5, 170),
    (47.1, 167.5),
]
LEAD = [(71.6, 156.4), (73.6, 164.8), (75.5, 174.1), (79.5, 181.7), (87.6, 185.6)]


def make_plate(im, masks):
    remove = np.maximum.reduce(masks)
    for pts, width in [
        (ARM0, 4.3),
        (ARM1, 4.3),
        (LEG0, 4.7),
        (LEG1, 4.7),
        ([NECK, (44, 127), (41, 142), HIP], 5.2),
        (HANDLE, 4.8),
        (LEAD, 4.8),
    ]:
        stroke(remove, pts, 255, width)
    ellipse(remove, (46.7, 211.6), (25, 7), 255)
    ellipse(remove, (87.8, 213.5), (23.6, 5.6), 255)
    remove = cv.dilate(remove, disk(4))
    plate = cv.inpaint(im, remove, 4 * S, cv.INPAINT_TELEA)
    # The grass/sidewalk boundary runs diagonally. Borrow pixels from the
    # same side of that edge when filling the large area exposed by the dog.
    # Sample clean strips at the sides of the same plane. A median across each
    # strip preserves the pavement edges and excludes grass tufts and codec noise.
    yy, xx = np.indices((H, W), dtype=np.float32)
    slope = np.interp(
        yy / S, [0, 140, 146, 192, 207, 256], [-0.094, -0.094, 0.277, 0.277, 0, 0]
    ).astype("float32")
    samples = []
    for center in (8.0, 135.0):
        band = []
        for dx in (-4, -2, 0, 2, 4):
            anchor = (center + dx) * S
            source_y = yy + (anchor - xx) * slope
            band.append(
                cv.remap(
                    im,
                    np.full_like(xx, anchor),
                    source_y,
                    cv.INTER_LINEAR,
                    borderMode=cv.BORDER_REFLECT_101,
                )
            )
        samples.append(np.median(band, axis=0))
    across = np.clip((xx / S - 10) / 124, 0, 1)[:, :, None]
    fill = samples[0] * (1 - across) + samples[1] * across
    amount = (
        np.clip((yy / S - 103.1) / 2.9, 0, 1)
        * cv.GaussianBlur(cv.dilate(remove, disk(3)), (11, 11), 2)
        / 255
    )
    plate = np.round(plate * (1 - amount[:, :, None]) + fill * amount[:, :, None]).astype("uint8")
    # Extend the surviving left house facade and roof into the covered area.
    face = cv.dilate(masks[0], disk(5))
    yy, xx = np.indices((H, W), dtype="float32")
    sample = cv.remap(
        im,
        np.float32(np.abs(2 * 34 * S - xx)),
        yy,
        cv.INTER_LINEAR,
        borderMode=cv.BORDER_REFLECT_101,
    )
    weight = (cv.GaussianBlur(face, (13, 13), 3) / 255) * np.clip((103.5 - yy / S) / 3, 0, 1)
    plate = (plate * (1 - weight[:, :, None]) + sample * weight[:, :, None]).round().astype("uint8")
    return plate


class DogMesh:
    def __init__(self, art):
        self.art = art
        self.points = []
        self.groups = []

        def mark(group, pts):
            self.points.extend(pts)
            self.groups.extend([group] * len(pts))

        mark("box", [(60, 157), (123, 157), (123, 220), (60, 220)])
        mark(
            "body",
            [
                (71, 192.8),
                (72, 195.5),
                (71, 199),
                (76, 201),
                (82.9, 201.7),
                (87, 202),
                (91.6, 201.5),
                (99.7, 201.3),
                (104.6, 198.7),
                (100, 195.5),
                (94, 194.4),
                (86.8, 189.9),
                (81.8, 188.2),
                (76.5, 189.4),
            ],
        )
        mark(
            "tail", [(62, 179), (65.8, 174.4), (67.2, 179.8), (68, 185), (69.9, 189.3), (65, 189.2)]
        )
        mark(
            "head",
            [
                (85.5, 168),
                (89.8, 164.7),
                (94, 164),
                (102.6, 159.7),
                (109.2, 162.4),
                (116.5, 167),
                (119.8, 175),
                (121.5, 184.4),
                (116, 190),
                (108, 192.8),
                (105.3, 196.6),
                (96, 195.5),
                (89.8, 191.5),
                (86, 186.9),
                (91, 181),
                (89, 174),
                (102, 173),
                (111.9, 180.2),
            ],
        )
        mark("ear", [(82, 173), (80, 179.7), (80.5, 184.8), (84.4, 186.1), (87, 182.3)])
        mark(
            "paw2",
            [(70.1, 202), (71.1, 211), (72, 215.2), (75.2, 215.5), (77.3, 209.8), (78.3, 203.7)],
        )
        mark(
            "paw0",
            [(79.1, 204.1), (80, 209.5), (82, 212.4), (85.3, 212), (86.3, 208.5), (86.6, 204.1)],
        )
        mark(
            "paw3",
            [(87.1, 203), (87.8, 211.9), (89.6, 216.8), (92.7, 217), (94.8, 211.4), (95, 204.7)],
        )
        mark(
            "paw1",
            [(97.4, 203.1), (98.3, 211.6), (100, 215), (103, 214.7), (105, 210), (105.8, 202)],
        )
        self.points = np.asarray(self.points)
        self.tri = Delaunay(self.points).simplices

    def draw(self, canvas, target):
        dst = np.asarray(target) * S
        lo = np.maximum(np.floor(dst.min(0) - 1).astype(int), [0, 0])
        hi = np.minimum(np.ceil(dst.max(0) + 2).astype(int), [W, H])
        if np.any(hi <= lo):
            return
        w, h = hi - lo
        maps = np.full((h, w, 2), -100, np.float32)
        for ids in self.tri:
            a, b, c = dst[ids] - lo
            xmin, ymin = np.maximum(np.floor(np.min([a, b, c], axis=0) - 1).astype(int), 0)
            xmax, ymax = np.minimum(np.ceil(np.max([a, b, c], axis=0) + 1).astype(int), [w, h])
            if xmax <= xmin or ymax <= ymin:
                continue
            yy, xx = np.ogrid[ymin:ymax, xmin:xmax]
            xx = xx - a[0]
            yy = yy - a[1]
            ax, ay = b - a
            bx, by = c - a
            det = ax * by - bx * ay
            if abs(det) < 1e-5:
                continue
            u = (xx * by - yy * bx) / det
            w2 = (yy * ax - xx * ay) / det
            inside = (u >= -0.008) & (w2 >= -0.008) & (u + w2 <= 1.008)
            source = self.points[ids] * S
            vals = (
                source[0]
                + u[:, :, None] * (source[1] - source[0])
                + w2[:, :, None] * (source[2] - source[0])
            )
            maps[ymin:ymax, xmin:xmax][inside] = vals[inside]
        tile = cv.remap(self.art, maps, None, cv.INTER_LINEAR, borderMode=cv.BORDER_CONSTANT)
        paste(canvas[lo[1] : hi[1], lo[0] : hi[0]], tile)


class OpeningRig:
    def __init__(self, opening):
        if opening.shape[:2] != (256, 144):
            raise ValueError("The traced opening drawing must be 144 by 256")
        cv.setRNGSeed(12)
        self.opening = opening.copy()
        self.src = cv.resize(opening, (W, H), interpolation=cv.INTER_CUBIC)
        masks = [
            cut(self.src, poly, margin)
            for poly, margin in [(FACE, 1.25), (DOG, 1.1)] + [(p, 0.8) for p in SHOES + HANDS]
        ]
        plate = make_plate(self.src, masks)
        self.head, dog, *self.ends = [sprite(self.src, m) for m in masks]
        self.mesh = DogMesh(dog)
        self.headmask = masks[0]
        self.yy, self.xx = np.indices((H, W), dtype=np.float32)
        self.action = DogWalk(performance="fall-and-recover")
        self.street = Panorama(plate, S)
        inner = cv.erode(self.headmask, disk(int(2.25 * S)))
        paper = np.array([250, 250, 249])
        mix = cv.GaussianBlur(inner, (7, 7), 1.5)[:, :, None].astype(float) / 255
        self.paper = np.rint((1 - mix) * self.src + mix * paper).astype(np.uint8)
        self.dog_mask = masks[1]
        keep = np.zeros((H, W), np.uint8)
        solid(
            keep,
            [
                (60, 157),
                (123, 157),
                (123, 196),
                (107, 197),
                (104, 200.5),
                (101, 203.3),
                (97, 205),
                (91, 205.8),
                (86, 204.6),
                (81, 204.5),
                (75, 203),
                (71, 200.9),
                (69, 193.1),
                (60, 193),
            ],
            255,
        )
        self.torso_alpha = cv.min(keep, self.dog_mask)

    @staticmethod
    def pt(z):
        return v(z.real, z.imag)

    def expression(self, t, f):
        transition = ease(t, 15, 23)
        if transition == 0:
            return self.head
        paper = self.paper.copy()
        ink = (23, 22, 23)
        shock = ease(t, 46, 54) * (1 - ease(t, 142, 148))
        tired = ease(t, 142, 149)
        closed = max(1 - ease(abs(t - q), 0, 2.4) for q in (44, 92, 138, 172, 208, 225))
        shut = max(closed, 0.83 * f.prone)
        voice = (0.5 + 0.5 * sin((t - 183) * 0.52)) * (1 - ease(t, 198, 205)) * ease(t, 182, 186)
        look = blend(1.6, 0.1, shock) + 0.52 * tired
        for j in range(2):
            eye = CENTER + v(-4.9 + 12.8 * j, -2.9 + 1.0 * j)
            w = 4.7 + 0.8 * shock
            h = (3.05 + 4.3 * shock - 0.58 * tired) * (1 - 0.93 * shut)
            outer = eye + v(-w, 0.0)
            end = eye + v(w, 0.5)
            if shock > 0.65 and shut < 0.28:
                cv.ellipse(
                    paper,
                    tuple(device(eye)),
                    tuple(device((w, h))),
                    -6,
                    0,
                    360,
                    ink,
                    max(1, round(0.82 * S)),
                    cv.LINE_AA,
                )
            else:
                curve(paper, outer, eye + v(0, -1.6 * h), end, ink, 0.88)
                curve(paper, outer, eye + v(0.15, 2.0 * h + 0.28), end, ink, 0.78)
            if h > 1.15:
                ellipse(
                    paper,
                    eye + v(look + 0.32 * sin(t * 0.19), min(1.1, 0.52 * h)),
                    (1.35, min(h * 0.58, 1.8)),
                    ink,
                )
            by = eye[1] - 6.0 - 3.25 * shock + 0.6 * tired
            curve(
                paper,
                v(eye[0] - w, by + 0.5 + (2.75 if j == 0 else -1.15) * tired),
                v(eye[0], by - 1.65 + 1.4 * (1 - shock) + 1.2 * tired),
                v(eye[0] + w, by + (2.8 if j == 1 else -1.3) * tired),
                ink,
                0.9,
            )
        mouth = CENTER + v(2.05, 10.1)
        # Open ink shape with an upper tooth edge and a low tongue.
        height = 1.55 + 4.75 * shock - 1.04 * tired + 2.4 * f.prone + 3.7 * voice
        width = 4.5 + 3.3 * shock + 0.8 * f.prone
        if height > 1.1:
            pts = [
                mouth + v(-width, 0.1),
                mouth + v(-0.70 * width, -0.63 * height),
                mouth + v(-0.15 * width, -height),
                mouth + v(0.53 * width, -0.96 * height),
                mouth + v(0.91 * width, -0.32 * height),
                mouth + v(width, 0.55),
                mouth + v(0.73 * width, 0.95 * height),
                mouth + v(0.14 * width, 1.08 * height),
                mouth + v(-0.61 * width, 0.64 * height),
            ]
            solid(paper, pts, ink)
            curve(
                paper,
                mouth + v(-width * 0.74, -height * 0.03),
                mouth + v(0, -height * 1.40),
                mouth + v(width * 0.68, -height * 0.58),
                (230, 230, 231),
                0.73,
            )
            if shock < 0.1 and tired < 0.1:
                curve(paper, mouth + v(-4.4, -1), mouth + v(1, 3.3), mouth + v(5.7, -1.1), ink, 1.0)
            if shock > 0.4:
                ellipse(
                    paper,
                    mouth + v(0.4, 0.64 * height),
                    (width * 0.53, height * 0.28),
                    (112, 105, 167),
                    -5,
                )
        else:
            curve(
                paper, mouth + v(-4.4, 0.6), mouth + v(-0.2, -2.5), mouth + v(4.9, 0.10), ink, 1.00
            )
        return cv.addWeighted(
            self.head, 1 - transition, sprite(paper, self.headmask), transition, 0
        )

    def shade(self, can, x, y, rx, ry, alpha):
        box = np.maximum(0, 1 - ((self.xx / S - x) / rx) ** 2 - ((self.yy / S - y) / ry) ** 2)
        can[:] = np.rint(can * (1 - alpha * box[:, :, None] ** 0.59)).astype(np.uint8)

    def draw_dog(self, can, t, f):
        ctr = self.pt(f.body.dog)
        phase = (t - 49) * 2 * pi / 12
        run = f.sprint
        turn = f.turn
        facing = cos(pi * turn)
        sign = 1 if facing >= 0 else -1
        width = 0.49 + 0.51 * abs(facing)
        zoom = 1 - 0.10 * ease(t, 55, 107) + 0.11 * ease(t, 133, 148)
        activity = run * (0.84 + 0.16 * cos(phase))
        actual = self.src.copy()
        pant = ease(t, 78, 110) * (1 - ease(t, 172, 182)) + 0.70 * f.dog_sit
        if pant > 0.06:
            mouth = v(110.8, 184)
            ellipse(actual, mouth, (3.9 + 1.3 * pant, 1.3 + 1.8 * pant), (38, 32, 39), -6)
            ellipse(actual, mouth + v(0.7, 1.45 * pant), (2.45, 1.12 * pant), (135, 126, 185))
        full_art = sprite(actual, self.dog_mask)
        torso = actual.copy()
        curve(torso, v(74, 202), v(89, 210.2), v(102, 203.1), (81, 75, 74), 0.62)
        bare_art = sprite(torso, self.torso_alpha)
        stride = ease(run, 0.08, 0.70)
        self.mesh.art = cv.addWeighted(full_art, 1 - stride, bare_art, stride, 0)

        def positions(side):
            pts = self.mesh.points.copy() - DOG_CENTER
            for j, (pt, group) in enumerate(zip(self.mesh.points, self.mesh.groups, strict=True)):
                if group.startswith("paw"):
                    weight = np.clip((pt[1] - 201) / 12, 0, 1)
                    pts[j, 1] -= 3.3 * f.dog_sit * weight
                    pts[j, 0] += 2.4 * f.dog_sit * weight
                elif group == "tail":
                    weight = np.clip((193 - pt[1]) / 15, 0, 1)
                    pts[j] += v(-2.5 * activity, 2.8 * sin(t * 0.31) * (0.36 + 0.64 * run)) * weight
                elif group == "ear":
                    pts[j] += v(-5 - 2.6 * sin(phase), -4.5 + 1.8 * cos(phase)) * run
                elif group == "head":
                    pts[j] += v(0.45, 0.75) * sin(phase - 0.4) * run
                # Let the haunches settle while the dog keeps looking toward the handler.
                hind = np.clip((99 - pt[0]) / 23, 0, 1)
                pts[j, 1] += f.dog_sit * hind * max(0, 1 - abs(pt[1] - 196) / 23) * 10.5
                if group in ("paw0", "paw2"):
                    pts[j, 0] += f.dog_sit * (3.8 + 2.3 * np.clip((pt[1] - 202) / 11, 0, 1))
            pts[:, 0] *= side * width * (1 + 0.12 * activity) * zoom
            pts[:, 1] *= zoom * (1 - 0.045 * activity)
            return pts + ctr

        if stride > 0.01:
            # Paired gallop. Each paw sweeps behind the body during stance,
            # folds high on recovery and extends forward before contact.
            for k, (x, shift) in enumerate(((-10, 0.49), (9, 0.03), (-12, 0.62), (10, 0.17))):
                ph = phase + 2 * pi * shift
                root = ctr + v(x, 2.5) * zoom
                tip = root + v(13.2 * sin(ph), 15.3 - 8.2 * max(0, cos(ph)))
                knee = blend(root, tip, 0.53) + v((-3.6 if x < 0 else 3.0), -3.4 - 2.0 * cos(ph))
                paw = tip + v(2.4, 0.5)
                dst = can.copy() if stride < 1 else can
                stroke(dst, [root, knee, tip, paw], (62, 58, 57), 4.45)
                stroke(
                    dst, [root, knee, tip, paw], (223, 222, 219) if k < 2 else (249, 248, 245), 3.00
                )
                if dst is not can:
                    cv.addWeighted(can, 1 - stride, dst, stride, 0, can)
        blend_turn = ease(turn, 0.40, 0.60)
        if 0 < blend_turn < 1:
            tmp = can.copy()
            self.mesh.draw(can, positions(1))
            self.mesh.draw(tmp, positions(-1))
            cv.addWeighted(can, 1 - blend_turn, tmp, blend_turn, 0, can)
        else:
            self.mesh.draw(can, positions(sign))

    def render(self, i):
        if i == 0:
            return self.opening.copy()
        p = pose(i, self.action)
        f = p.fall
        t = p.t
        b = f.body
        neck, hip, center, free, grip = [
            self.pt(x) for x in (b.neck, b.hip, b.face, b.free, b.grip)
        ]
        dog = self.pt(b.dog)
        can = self.street.frame(f.camera)
        ground = 211 - 18 * ease(t, 49, 143)
        self.shade(
            can,
            hip[0] + 6,
            ground + 1,
            22 - 6 * f.lift + 8 * f.prone,
            4.4 - 0.9 * f.lift,
            0.135 - 0.065 * f.lift,
        )
        self.shade(
            can,
            dog[0] - 0.5,
            dog[1] + 19 + 2.9 * f.sprint * cos((t - 50) * 2 * pi / 12),
            21,
            3.5,
            0.115,
        )
        flash = ease(t, 144, 147) * (1 - ease(t, 149, 155))
        if flash > 0.002:
            overlay = can.copy()
            angles = np.arange(22) * 2 * pi / 22
            radii = np.where(np.arange(22) % 2 == 0, 1, 0.64)
            outline = np.stack(
                (79 + 43 * np.cos(angles) * radii, 205 + 10.7 * np.sin(angles) * radii), axis=1
            )
            solid(overlay, outline, (241, 243, 244))
            stroke(overlay, np.vstack((outline, outline[0])), (209, 213, 211), 0.58)
            cv.addWeighted(can, 1 - flash, overlay, flash, 0, can)
        # Short parallel streaks are a separate drawing layer, only during the fast pull.
        strength = (ease(t, 49, 55) - ease(t, 78, 87)) * 0.37
        if strength > 0.01:
            layer = can.copy()
            for j in range(9):
                x = ((j * 38.1 - t * (4.1 + 0.18 * j)) % 184) - 22
                y = [28, 45, 58, 103, 117, 145, 211, 219, 229][j]
                dy = (-0.27 if y < 80 else 0.04 if y < 150 else 0.37) * (20 + j)
                stroke(
                    layer, [(x, y), (x + 20 + j, y + dy)], (244, 243, 230), 0.55 if j % 3 else 0.95
                )
            cv.addWeighted(can, 1 - strength, layer, strength, 0, can)
        end = self.pt(f.lead_end)
        ctrl = self.pt(f.lead_control)
        latch = self.pt(f.collar)
        rope = (48, 53, 71)
        cord = (61, 72, 116)
        curve(can, end, ctrl, latch, rope, 1.56)
        curve(can, end, ctrl, latch, cord, 0.72)
        loop = np.array(HANDLE)
        drop = f.slack
        initial = end + (loop - GRIP) * v(1 - 0.73 * f.lift, 1 - 0.83 * f.lift)
        theta = np.linspace(0, 2 * pi, len(loop))
        groundloop = end + np.c_[6.4 * np.cos(theta) - 5.6, 1.3 * np.sin(theta) - 0.5]
        coil = end + np.c_[4.4 * np.cos(theta) - 0.6, 2.0 * np.sin(theta)]
        path = blend(blend(initial, groundloop, drop), coil, f.release)
        # As the lead straightens, the handle pulls into the gripping palm.
        path = end + (path - end) * (1 - 0.78 * f.lift)
        red = blend(np.array(cord), np.array((94, 94, 162)), f.release)
        stroke(can, path, rope, 1.62 if f.release < 0.1 else 1.0)
        stroke(can, path, tuple(red.tolist()), 0.68)
        recoil = ease(t, 143, 148) * (1 - ease(t, 168, 178))
        if recoil > 0.02:
            a = np.linspace(0, 3.8 * pi, 46)
            spring = (
                end
                + np.c_[(-9 + 0.80 * a + 4.2 * np.cos(a)) * recoil, (-2 + 2.5 * np.sin(a)) * recoil]
            )
            stroke(can, spring, (110, 104, 161), 0.85)
        self.draw_dog(can, t, f)
        ink = (23, 22, 22)
        for j, (k, ankle) in enumerate(((b.far_knee, b.far_foot), (b.near_knee, b.near_foot))):
            foot = self.pt(ankle)
            stroke(can, [hip, self.pt(k), foot], ink, 1.55 if j == 0 else 1.7)
            angle = (
                (-0.40 + 0.32 * j) * f.lift
                + (-0.20 if j == 0 else 0.25) * f.prone
                + 0.11 * f.seated
            )
            # The trailing shoes turn away from camera during flight and on the ground.
            if f.lift + f.prone > 0.32:
                stretch = 0.67 + 0.33 * (1 - max(f.lift, f.prone))
                A = rotate(angle) @ np.diag([stretch, 1.0])
                dst = foot + A @ v(2.4, -0.35)
                ellipse(can, dst, (3.8, 1.55), ink, angle * 180 / pi)
            else:
                place(can, self.ends[j], FEET[j], foot, angle, 1 - 0.20 * f.seated)
        curve(
            can,
            neck,
            blend(neck, hip, 0.62) + v(-1.8 * (1 - f.prone), 0.3 * f.prone),
            hip,
            ink,
            1.85,
        )
        for j, wrist in enumerate((free, grip)):
            hand0 = FREE if j == 0 else GRIP
            elbow0 = v(37.2, 141.6) if j == 0 else v(57, 139.8)
            elbow = blend(neck, wrist, 0.53) + (elbow0 - blend(NECK, hand0, 0.53)) * (
                1 - ease(t, 12, 23)
            )
            elbow += v(-2.6, 2.1) * f.lift
            recovery_arm = ease(t, 143, 148) * (1 - ease(t, 173, 180))
            if recovery_arm:
                anchored = v(44.5, 209) if j == 0 else v(96, 202)
                elbow = blend(elbow, anchored, recovery_arm)
            if f.seated:
                desired = (
                    blend(neck, wrist, 0.65) + v(-3, 0)
                    if j == 0
                    else blend(neck, wrist, 0.56) + v(6, 10)
                )
                elbow = blend(elbow, desired, f.seated)
            stroke(can, [neck, elbow, wrist], ink, 1.45)
            opened = (f.lift if j == 0 else 0) + f.prone
            if opened > 0.18:
                heading = wrist - elbow
                heading = heading / max(1, np.linalg.norm(heading))
                side = v(-heading[1], heading[0])
                ellipse(can, wrist, (2.2, 1.65), ink)
                for finger in (-1, 0, 1):
                    stroke(
                        can,
                        [
                            wrist + side * finger * 0.7,
                            wrist + heading * (3.8 - 0.55 * abs(finger)) + side * 1.65 * finger,
                        ],
                        ink,
                        0.83,
                    )
            else:
                place(
                    can,
                    self.ends[2 + j],
                    hand0,
                    wrist,
                    -0.3 * f.lift,
                    0.75 + 0.25 * (1 - ease(t, 12, 24)),
                )
        headzoom = 1 - 0.16 * (ease(t, 50, 81) - ease(t, 142, 150))
        angle = (
            -0.12 * f.lift
            + 0.10 * f.prone
            + 0.045 * f.seated
            + 0.095 * (ease(t, 2, 9) - ease(t, 16, 23))
        )
        place(can, self.expression(t, f), CENTER, center, angle, headzoom)
        if i < 4:
            can = cv.addWeighted(self.src, 1 - ease(i, 0, 4), can, ease(i, 0, 4), 0)
        return cv.resize(can, (144, 256), interpolation=cv.INTER_AREA)
