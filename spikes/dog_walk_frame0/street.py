"""A continuous, illustrated street extension, lit and textured from the opening frame."""

import math

import cv2 as cv
import numpy as np


class Panorama:
    def __init__(self, plate, scale):
        self.s = scale
        s = scale
        width = 600
        height = 256
        self.rng = np.random.default_rng(2205)
        # Paint in RGB, then store one BGR plate for fast camera sampling.
        self.bg = np.zeros((height * s, width * s, 3), np.uint8)
        top = cv.cvtColor(plate, cv.COLOR_BGR2RGB)
        for y in range(256 * s):
            c = tuple(int(i) for i in np.median(top[min(y, 55 * s), 72 * s : 77 * s], axis=0))
            self.bg[y] = c
        self.foliage = top[4 * s : 23 * s, 129 * s : 142 * s].copy()
        self.sky_cloud(
            top,
            [
                (170, 17, 0.64),
                (235, 38, 0.40),
                (312, 17, 0.69),
                (382, 35, 0.42),
                (458, 12, 0.54),
                (532, 27, 0.42),
                (588, 8, 0.64),
            ],
        )
        self.poly([(0, 100), (600, 99), (600, 151), (0, 151)], (154, 150, 152))
        self.poly(
            [
                (0, 142),
                (105, 133),
                (180, 130),
                (257, 137),
                (340, 129),
                (427, 135),
                (568, 127),
                (600, 129),
                (600, 256),
                (0, 256),
            ],
            (145, 173, 111),
        )
        self.line(
            [
                (0, 140),
                (105, 131),
                (180, 128),
                (257, 135),
                (340, 127),
                (427, 133),
                (568, 125),
                (600, 127),
            ],
            (205, 204, 191),
            3.2,
        )
        # The near and far edges of the sidewalk are separate from the moving actors.
        self.poly(
            [
                (0, 152),
                (98, 179),
                (155, 183),
                (218, 162),
                (283, 175),
                (351, 159),
                (399, 162),
                (427, 154),
                (485, 144),
                (508, 144),
                (580, 181),
                (600, 183),
                (600, 256),
                (0, 256),
            ],
            (206, 203, 197),
        )
        self.poly([(0, 219), (72, 256), (0, 256)], (123, 150, 103))
        self.poly([(155, 216), (240, 256), (98, 256)], (139, 164, 105))
        self.poly([(288, 228), (343, 256), (244, 256)], (141, 166, 104))
        self.poly([(389, 214), (493, 256), (341, 256)], (141, 166, 105))
        self.poly(
            [(508, 148), (540, 145), (600, 151), (600, 194), (574, 193), (523, 179), (491, 167)],
            (140, 168, 105),
        )
        self.line([(351, 159), (399, 162), (427, 154), (485, 144)], (177, 177, 154), 0.8)
        for x in [172, 260, 340, 418, 506, 587]:
            self.line([(x - 47, 181), (x + 24, 164), (x + 51, 159)], (153, 152, 143), 0.9)
            self.line([(x - 42, 220), (x + 13, 205), (x + 29, 199)], (165, 161, 152), 0.65)
            self.line([(x + 8, 256), (x + 77, 223)], (153, 151, 141), 0.8)
        for _ in range(800):
            x = int(self.rng.integers(1, width - 2))
            y = int(self.rng.integers(137, 255))
            col = self.bg[y * s, x * s].astype(int)
            if col[1] - col[2] > 31:
                if self.rng.random() < 0.24:
                    self.line(
                        [
                            (x - 1, y),
                            (x - 1.8, y - 1.3),
                            (x, y - 0.3),
                            (x + 0.6, y - 2),
                            (x + 1.1, y - 0.4),
                            (x + 2, y - 1),
                        ],
                        tuple(np.maximum(0, col - 13).tolist()),
                        0.44,
                    )
            else:
                self.oval(
                    x, y, self.rng.uniform(0.4, 1.6), 0.40, tuple(np.maximum(0, col - 9).tolist())
                )
        self.horizon()
        self.source_houses(top)
        self.tree(243, 207, 1.0)
        # The near tree crosses the frame faster than the far house band.
        # Keep it on its own transparent plane so it can leave the shot fully.
        ground = self.bg
        self.bg = np.zeros_like(ground)
        self.tree(429, 190, 0.9)
        self.near = cv.GaussianBlur(cv.cvtColor(self.bg, cv.COLOR_RGB2BGR), (3, 3), 0.65)
        tree_mask = (np.max(self.bg, axis=2) > 0).astype(np.uint8) * 255
        self.near_alpha = cv.GaussianBlur(tree_mask, (3, 3), 0.65)
        self.bg = ground
        self.tree(570, 130, 0.92, 43)
        self.lamp(505, 168)
        self.bg = cv.GaussianBlur(self.bg, (3, 3), 0.65)
        bg = cv.cvtColor(self.bg, cv.COLOR_RGB2BGR)
        # Retain all original plate pixels within the opening viewport. Gradually
        # transition using a narrow reflected edge outside the opening.
        bg[:, : 144 * s] = plate
        strip = 14 * s
        a = np.linspace(1, 0, strip)[None, :, None]
        bg[:, 144 * s : 144 * s + strip] = np.rint(
            plate[:, -strip:][:, ::-1] * a + bg[:, 144 * s : 144 * s + strip] * (1 - a)
        ).astype(np.uint8)
        sky_w = 46 * s
        sky_h = 53 * s
        ay = np.clip((sky_h - np.arange(sky_h)) / (9 * s), 0, 1)[:, None]
        ax = np.clip((sky_w - np.arange(sky_w)) / (10 * s), 0, 1)[None, :]
        sky_alpha = (ax * ay)[:, :, None]
        sky_roi = bg[:sky_h, 144 * s : 144 * s + sky_w]
        sky_roi[:] = np.rint(
            sky_roi * (1 - sky_alpha) + plate[:sky_h, -sky_w:][:, ::-1] * sky_alpha
        ).astype(np.uint8)
        self.bg = bg
        self.yy, self.xx = np.indices((256 * s, 144 * s), dtype="float32")

    def poly(self, pts, col):
        cv.fillPoly(self.bg, [np.rint(np.array(pts) * self.s).astype(np.int32)], col, cv.LINE_AA)

    def line(self, pts, col, w):
        cv.polylines(
            self.bg,
            [np.rint(np.array(pts) * self.s).astype(np.int32)],
            False,
            col,
            max(1, round(w * self.s)),
            cv.LINE_AA,
        )

    def oval(self, x, y, rx, ry, col):
        cv.ellipse(
            self.bg,
            (round(x * self.s), round(y * self.s)),
            (max(1, round(rx * self.s)), max(1, round(ry * self.s))),
            0,
            0,
            360,
            col,
            -1,
            cv.LINE_AA,
        )

    def sky_cloud(self, img, clouds):
        s = self.s
        cloud = img[7 * s : 36 * s, 0 : 66 * s].copy()
        mask = np.clip((cloud[:, :, 0].astype(float) - 173) / 56, 0, 1).astype("float32")
        for x, y, scale in clouds:
            c = cv.resize(cloud, None, fx=scale, fy=scale)
            alpha = cv.resize(mask, (c.shape[1], c.shape[0]))[:, :, None]
            dst = self.bg[
                round(y * s) : round(y * s) + c.shape[0], round(x * s) : round(x * s) + c.shape[1]
            ]
            h, w = dst.shape[:2]
            dst[:] = dst * (1 - alpha[:h, :w]) + c[:h, :w] * alpha[:h, :w]

    def source_houses(self, src):
        # Reuse the facade materials from the first drawing on the far sidewalk.
        s = self.s
        for polygon, left, upper, w, h, target in [
            (
                [(1, 77), (16, 57), (49, 60), (62, 77), (62, 101), (2, 101)],
                0,
                55,
                64,
                48,
                (458, 69, 63, 37),
            ),
            (
                [(109, 86), (123, 70), (131, 67), (143, 70), (143, 101), (111, 101)],
                108,
                65,
                36,
                39,
                (523, 67, 43, 40),
            ),
        ]:
            mask = np.zeros(src.shape[:2], np.uint8)
            cv.fillPoly(mask, [np.rint(np.asarray(polygon) * s).astype(np.int32)], 255, cv.LINE_AA)
            shape = slice(upper * s, (upper + h) * s), slice(left * s, (left + w) * s)
            x, y, dw, dh = target
            tile = cv.resize(src[shape], (dw * s, dh * s))
            a = cv.resize(mask[shape], (dw * s, dh * s))[:, :, None] / 255.0
            roi = self.bg[y * s : (y + dh) * s, x * s : (x + dw) * s]
            roi[:] = np.rint(roi * (1 - a) + tile * a).astype(np.uint8)

    def horizon(self):
        r = self.rng
        for x in range(134, 611, 5):
            h = r.uniform(5, 15)
            self.oval(x, 93 - h * 0.2, 6, h, (142, 167, 136))
        for x, w, h, style in [
            (147, 32, 21, 1),
            (181, 30, 19, 0),
            (221, 44, 29, 2),
            (263, 29, 16, 1),
            (300, 33, 20, 2),
            (336, 27, 24, 0),
            (365, 41, 19, 1),
            (396, 32, 21, 2),
            (422, 26, 16, 0),
            (449, 37, 25, 0),
            (464, 55, 30, 1),
            (521, 38, 22, 2),
            (553, 26, 19, 1),
            (584, 45, 26, 2),
        ]:
            base = 105 - (x % 7) * 0.2
            roof = [(111, 127, 138), (99, 111, 124), (145, 99, 76)][style]
            wall = [(204, 207, 199), (202, 211, 207), (224, 204, 172)][style]
            self.poly(
                [
                    (x, base),
                    (x, base - h * 0.62),
                    (x + w * 0.28, base - h),
                    (x + w * 0.57, base - h * 0.62),
                    (x + w, base - h * 0.62),
                    (x + w, base),
                ],
                wall,
            )
            self.poly(
                [
                    (x - 1, base - h * 0.63),
                    (x + w * 0.28, base - h - 1),
                    (x + w * 0.78, base - h - 0.3),
                    (x + w + 1, base - h * 0.63),
                    (x + w * 0.56, base - h * 0.61),
                    (x + w * 0.28, base - h + 2),
                ],
                roof,
            )
            if style == 1:
                for frac in (0.56, 0.75):
                    xx = x + frac * w
                    yy = base - h * 0.77
                    self.poly(
                        [
                            (xx - w * 0.07, yy),
                            (xx, yy - h * 0.16),
                            (xx + w * 0.07, yy),
                            (xx + w * 0.07, yy + h * 0.14),
                            (xx - w * 0.07, yy + h * 0.14),
                        ],
                        wall,
                    )
                    self.line(
                        [(xx - w * 0.08, yy), (xx, yy - h * 0.16), (xx + w * 0.08, yy)],
                        (83, 100, 107),
                        0.75,
                    )
                    self.line([(xx, yy + 0.25), (xx, yy + h * 0.11)], (101, 120, 119), 1.15)
            self.line(
                [
                    (x + 1, base - h * 0.60),
                    (x + w * 0.28, base - h + 1),
                    (x + w * 0.55, base - h * 0.60),
                ],
                (124, 130, 122),
                1,
            )
            for wx in (0.14, 0.35, 0.66, 0.83):
                for wy in [0.43] if h < 23 else [0.46, 0.21]:
                    xx = x + w * wx
                    yy = base - h * wy
                    ww = w * 0.085
                    hh = h * 0.17
                    self.poly(
                        [(xx, yy), (xx + ww, yy), (xx + ww, yy + hh), (xx, yy + hh)],
                        (110, 123, 121),
                    )
                    self.line(
                        [(xx + ww * 0.52, yy + 0.3), (xx + ww * 0.52, yy + hh - 0.3)],
                        (192, 197, 182),
                        0.42,
                    )
                    self.line(
                        [(xx + 0.3, yy + hh * 0.5), (xx + ww - 0.3, yy + hh * 0.5)],
                        (186, 193, 180),
                        0.42,
                    )
            self.poly(
                [
                    (x + w * 0.50, base - h * 0.31),
                    (x + w * 0.62, base - h * 0.31),
                    (x + w * 0.62, base),
                    (x + w * 0.50, base),
                ],
                (142, 136, 118),
            )
            self.oval(x + w * 0.22, base - 0.3, w * 0.22, 1.8, (110, 139, 103))
        for x in [166, 208, 279, 328, 367, 439, 452, 526, 589]:
            h = r.uniform(11, 22)
            self.line([(x, 106), (x, 95 - h * 0.5)], (142, 125, 98), 1.4)
            self.oval(x, 94 - h * 0.5, h * 0.44, h * 0.60, (128, 154, 112))
            for _ in range(13):
                dx = r.uniform(-0.36, 0.36) * h
                dy = r.uniform(-0.38, 0.35) * h
                self.oval(
                    x + dx,
                    92 - h * 0.5 + dy,
                    h * 0.16,
                    h * 0.19,
                    (128 + int(r.integers(0, 12)), 155 + int(r.integers(0, 10)), 114),
                )
        self.line(
            [(143, 107), (235, 106), (301, 108), (374, 105), (430, 107), (501, 110), (600, 106)],
            (192, 191, 174),
            1.3,
        )
        self.line(
            [(145, 110), (232, 109), (303, 111), (378, 108), (428, 110), (506, 113), (600, 109)],
            (217, 212, 197),
            0.75,
        )

    def tree(self, x, b, k, canopy_shift=0):
        r = self.rng

        def pt(dx, dy):
            return (x + dx * k, b + dy * k)

        def shape(coords, color):
            self.poly([pt(a, z) for a, z in coords], color)

        shape(
            [
                (-14, 0),
                (-8, -4),
                (-5, -30),
                (-4, -82),
                (-10, -113),
                (-27, -143),
                (-25, -148),
                (-12, -129),
                (-7, -123),
                (-11, -164),
                (-6, -165),
                (1, -119),
                (13, -148),
                (18, -147),
                (5, -109),
                (10, -115),
                (31, -142),
                (36, -142),
                (20, -116),
                (5, -97),
                (6, -51),
                (7, -8),
                (12, -1),
            ],
            (109, 88, 66),
        )
        shape(
            [
                (-8, -2),
                (-4, -10),
                (-2, -66),
                (-2, -95),
                (0, -118),
                (4, -101),
                (3, -53),
                (3, -8),
                (0, -1),
            ],
            (135, 102, 73),
        )
        self.line([pt(-1, -12), pt(1, -52), pt(-1, -88)], (151, 116, 83), 1.4 * k)
        # Overlapping lower masses and smaller irregular contour lobes create a canopy.
        for dx, dy, rx, ry in [
            (-32, -154, 33, 27),
            (-50, -167, 24, 24),
            (-8, -172, 39, 35),
            (27, -161, 36, 31),
            (46, -178, 29, 30),
            (0, -193, 42, 34),
        ]:
            for j in range(13):
                a = 2 * math.pi * j / 13
                side = r.uniform(0.83, 1.02)
                cx, cy = pt(
                    dx + rx * 0.76 * math.cos(a) * side,
                    dy + canopy_shift + ry * 0.70 * math.sin(a) * side,
                )
                col = (
                    75 + int(r.integers(-4, 7)),
                    108 + int(r.integers(-4, 8)),
                    70 + int(r.integers(-4, 4)),
                )
                self.oval(cx, cy, rx * k * 0.34, ry * k * 0.38, col)
            cx, cy = pt(dx, dy + canopy_shift)
            self.oval(cx, cy, rx * k * 0.87, ry * k * 0.86, (79, 112, 72))
        for _ in range(100):
            u = r.uniform(-1, 1)
            z = r.uniform(-1, 1)
            if u * u + z * z > 1:
                continue
            cx, cy = pt(u * 62, -177 + z * 25 + canopy_shift)
            base = 91 + int(r.integers(-8, 11))
            self.oval(cx, cy, r.uniform(3, 9) * k, r.uniform(2, 6) * k, (base, base + 34, base - 7))
        # Transfer the opening tree's brush texture into the new foliage.
        x0 = max(0, int((x - 75 * k) * self.s))
        x1 = min(self.bg.shape[1], int((x + 81 * k) * self.s))
        y1 = max(0, int((b + (-120 + canopy_shift) * k) * self.s))
        if x1 > x0 and y1:
            roi = self.bg[:y1, x0:x1]
            tex = cv.resize(self.foliage, None, fx=1.6, fy=1.6, interpolation=cv.INTER_CUBIC)
            tex = cv.copyMakeBorder(tex, 0, tex.shape[0], 0, tex.shape[1], cv.BORDER_REFLECT_101)
            tex = np.tile(
                tex,
                (
                    (y1 + tex.shape[0] - 1) // tex.shape[0],
                    (x1 - x0 + tex.shape[1] - 1) // tex.shape[1],
                    1,
                ),
            )[:y1, : x1 - x0]
            green = (
                (roi[:, :, 1].astype(float) - roi[:, :, 0] > 17)
                & (roi[:, :, 1].astype(float) - roi[:, :, 2] > 15)
                & (roi[:, :, 0] < 116)
            )
            shade = (tex.astype(float) - np.median(self.foliage, axis=(0, 1))) * 0.36
            roi[:] = np.clip(roi + green[:, :, None] * shade, 0, 255).astype(np.uint8)
        self.oval(x + 1, b + 0.2, 15 * k, 1.6 * k, (116, 128, 89))

    def lamp(self, x, base):
        shade = (49, 69, 60)
        light = (78, 98, 79)
        self.poly(
            [
                (x - 7, base),
                (x - 7, base - 3),
                (x - 4, base - 5),
                (x - 3.7, base - 36),
                (x - 5, base - 39),
                (x - 4, base - 43),
                (x - 3, base - 45),
                (x - 2.2, 13),
                (x - 3.2, 10),
                (x - 3, 8),
                (x + 3, 8),
                (x + 3, 11),
                (x + 2.1, 13),
                (x + 2.2, base - 45),
                (x + 4.2, base - 42),
                (x + 4.2, base - 38),
                (x + 3.3, base - 35),
                (x + 4.2, base - 5),
                (x + 7, base - 3),
                (x + 7, base),
            ],
            shade,
        )
        self.line([(x - 1, 15), (x - 1.5, base - 43)], light, 0.75)
        self.oval(x, base - 39, 5, 2.2, (57, 77, 62))
        self.oval(x, base - 2, 7.8, 2.2, shade)
        self.poly(
            [(x - 4, 9), (x - 8, -2), (x - 9, -7), (x + 8, -7), (x + 7, -2), (x + 3, 9)], shade
        )
        self.poly([(x - 3, 7), (x - 6, -4), (x - 1, -4), (x, 7)], (228, 215, 167))
        self.poly([(x + 1, 7), (x + 1, -4), (x + 6, -4), (x + 3, 7)], (207, 207, 170))

    def frame(self, pan):
        base = cv.remap(
            self.bg,
            self.xx + np.float32(pan * self.s),
            self.yy,
            cv.INTER_LINEAR,
            borderMode=cv.BORDER_REPLICATE,
        )
        near_x = self.xx + np.float32((pan + 0.86 * (pan - 327)) * self.s)
        layer = cv.remap(self.near, near_x, self.yy, cv.INTER_LINEAR, borderMode=cv.BORDER_CONSTANT)
        mask = cv.remap(
            self.near_alpha, near_x, self.yy, cv.INTER_LINEAR, borderMode=cv.BORDER_CONSTANT
        )
        return np.clip(layer.astype(float) + base * (1 - mask[:, :, None] / 255.0), 0, 255).astype(
            "uint8"
        )
