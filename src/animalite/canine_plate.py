"""Sample a landscape with slower distant scenery and a world-locked running surface."""

from __future__ import annotations

from math import ceil
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from animalite.errors import ValidationRejected
from animalite.proc import run_capture


class RunningLane:
    def __init__(self, binary: str, path: Path, width: int, ink: bool, timeout: float):
        plate_width = max(640, ceil(width * 1.35))
        filters = (
            f"scale={plate_width}:360:force_original_aspect_ratio=increase,"
            f"crop={plate_width}:360:(iw-ow)/2:ih-oh,setsar=1"
        )
        if ink:
            filters += ",gblur=sigma=1.15"
        result = run_capture(
            [
                binary,
                "-v",
                "error",
                "-nostdin",
                "-i",
                str(path),
                "-vf",
                filters,
                "-frames:v",
                "1",
                "-threads",
                "1",
                "-pix_fmt",
                "rgb24",
                "-f",
                "rawvideo",
                "-",
            ],
            timeout=timeout,
        )
        if result.returncode or result.survivors or len(result.stdout) != plate_width * 360 * 3:
            raise ValidationRejected(f"unable to decode running-lane backdrop: {path.name}")
        plate = np.frombuffer(result.stdout, np.uint8).reshape(360, plate_width, 3)
        if ink:
            luma = np.sum(plate.astype(np.float32) * [0.26, 0.60, 0.14], axis=2)
            dy, dx = np.gradient(luma)
            edge = np.clip((np.hypot(dx, dy) - 7) / 26, 0, 1)
            wash = np.floor(luma / 35) * 4
            shade = wash - 95 * edge
            plate = np.clip(np.array([224, 222, 210]) + shade[:, :, None], 0, 255).astype(np.uint8)
        self.plate = plate
        self.row = np.arange(360)[:, None]
        self.x = np.arange(width)[None, :] + (plate_width - width) * 0.40
        self.rate = np.interp(
            self.row,
            [0, 222, 235, 260, 276, 359],
            [0.21, 0.21, 0.28, 0.72, 1, 1],
        )

    def sample(self, pan: float) -> NDArray[np.uint8]:
        limit = self.plate.shape[1] - 1
        pos = limit - np.abs((self.x + pan * self.rate) % (2 * limit) - limit)
        left = np.floor(pos).astype(np.intp)
        weight = (pos - left)[:, :, None]
        right = np.minimum(left + 1, limit)
        pixels: NDArray[np.uint8] = np.rint(
            self.plate[self.row, left] * (1 - weight) + self.plate[self.row, right] * weight
        ).astype(np.uint8)
        return pixels
