"""Single-frame image encoding through the installed FFmpeg.

Used by the fixture generator to write synthetic anchors and by the RIFE
adapter to hand normalized anchors to a runtime whose interface is file-based.
Keeping it here means there is exactly one PNG writer and it goes through the
same external tool as the rest of the media path.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from animalite.errors import AdapterError
from animalite.media.ffmpeg import FFmpegTools

__all__ = ["write_png_rgb24"]


def write_png_rgb24(
    tools: FFmpegTools,
    frame: NDArray[np.uint8],
    destination: Path,
    *,
    timeout: float = 60.0,
) -> Path:
    """Write one RGB24 frame to a PNG losslessly.

    ``-compression_level 9 -pred none`` keeps the output byte-reproducible for a
    given frame, which is what makes the fixture generator's hashes stable.
    """
    if frame.ndim != 3 or frame.shape[2] != 3 or frame.dtype != np.uint8:
        raise AdapterError(
            f"expected an (h, w, 3) uint8 frame; got shape {frame.shape} dtype {frame.dtype}"
        )
    height, width, _ = frame.shape
    argv = [
        tools.ffmpeg_path,
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{width}x{height}",
        "-i",
        "-",
        "-frames:v",
        "1",
        "-compression_level",
        "9",
        "-pred",
        "none",
        "-f",
        "image2",
        "-c:v",
        "png",
        str(destination),
    ]
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        completed = subprocess.run(  # noqa: S603 - argv list, no shell
            argv, input=frame.tobytes(), capture_output=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise AdapterError(f"writing {destination} timed out after {timeout}s") from exc
    if completed.returncode != 0 or not destination.exists():
        raise AdapterError(
            f"failed to write {destination}: exit {completed.returncode}; "
            f"{completed.stderr.decode('utf-8', 'replace').strip()[-500:]}"
        )
    return destination
