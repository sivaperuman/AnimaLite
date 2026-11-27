"""Render the dog-walk development shot from its first displayed picture."""

import argparse
import os
import shutil
import tempfile
import time
from pathlib import Path

import cv2 as cv
import numpy as np
from rig import OpeningRig

from animalite.dog_walk import FPS, FRAMES
from animalite.proc import run_capture


def render(source: Path, output: Path, deadline: float) -> None:
    if output.exists():
        raise FileExistsError(output)
    binary = shutil.which("ffmpeg")
    if not binary:
        raise FileNotFoundError("ffmpeg")

    def remaining() -> float:
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise TimeoutError("dog-walk render exceeded its deadline")
        return seconds

    def ffmpeg(*args: str) -> bytes:
        result = run_capture([binary, "-nostdin", "-v", "error", *args], timeout=remaining())
        if result.returncode or result.survivors:
            raise RuntimeError(result.stderr.decode(errors="replace") or "FFmpeg failed")
        return result.stdout

    opening = ["-i", str(source), "-map", "0:v:0", "-frames:v", "1", "-threads", "1"]
    png = ffmpeg(*opening, "-c:v", "png", "-f", "image2pipe", "-")
    image = cv.imdecode(np.frombuffer(png, np.uint8), cv.IMREAD_COLOR)
    if image is None or image.shape[:2] != (256, 144):
        raise ValueError("expected this shot's 144 by 256 first frame")
    first_yuv = ffmpeg(*opening, "-pix_fmt", "yuv420p", "-f", "rawvideo", "-")
    native = ["-f", "rawvideo", "-s", "144x256", "-r", str(FPS)]
    rig = OpeningRig(image)

    with tempfile.TemporaryDirectory(dir=output.parent) as scratch:
        folder = Path(scratch)
        bgr, yuv, movie = (folder / name for name in ("pictures.bgr", "pictures.yuv", "out.mp4"))
        # Write frames one at a time. The temporary files bound RAM use and
        # keep an interrupted render from publishing a partial MP4.
        with bgr.open("wb") as stream:
            for i in range(FRAMES):
                remaining()
                stream.write(rig.render(i).tobytes())
        ffmpeg(
            *native,
            "-pix_fmt",
            "bgr24",
            "-i",
            str(bgr),
            "-vf",
            "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
            "-threads",
            "1",
            "-f",
            "rawvideo",
            str(yuv),
        )
        if yuv.stat().st_size != FRAMES * len(first_yuv):
            raise ValueError("native frame count or opening pixel format mismatch")
        with yuv.open("r+b") as raw:
            raw.write(first_yuv)
        ffmpeg(
            *native,
            "-pix_fmt",
            "yuv420p",
            "-i",
            str(yuv),
            "-vf",
            "setparams=range=limited:color_primaries=bt709:color_trc=bt709:colorspace=bt709",
            "-c:v",
            "libx264",
            "-qp",
            "0",
            "-preset",
            "medium",
            "-threads",
            "2",
            "-x264-params",
            "colorprim=bt709:transfer=bt709:colormatrix=bt709",
            "-movflags",
            "+faststart",
            str(movie),
        )
        os.link(movie, output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=300)
    options = parser.parse_args()
    render(options.source, options.output, time.monotonic() + options.timeout_seconds)
