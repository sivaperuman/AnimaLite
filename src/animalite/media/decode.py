"""CPU decode of approved anchor images into raw RGB24 buffers.

Anchors are decoded with the same externally installed FFmpeg that encodes the
output, so the "real execution path" rule holds for input handling too. Frames
are returned as ``numpy`` arrays shaped ``(height, width, 3)``, ``uint8``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from animalite.errors import AdapterError
from animalite.media.ffmpeg import FFmpegTools

__all__ = ["decode_image_rgb24"]


def decode_image_rgb24(
    tools: FFmpegTools,
    path: Path,
    *,
    width: int,
    height: int,
    timeout: float = 60.0,
) -> NDArray[np.uint8]:
    """Decode one image to RGB24, scaling to ``width`` x ``height`` on the CPU.

    The scaler is pinned (``flags=bicubic``, full-range RGB output) so anchor
    normalization is repeatable across runs (MR-009).
    """
    argv = [
        tools.ffmpeg_path,
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-i",
        str(path),
        "-vf",
        f"scale={width}:{height}:flags=bicubic",
        "-frames:v",
        "1",
        "-pix_fmt",
        "rgb24",
        "-f",
        "rawvideo",
        "-",
    ]
    try:
        completed = subprocess.run(  # noqa: S603 - argv list, no shell
            argv,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise AdapterError(f"decoding {path} timed out after {timeout}s") from exc

    expected = width * height * 3
    if completed.returncode != 0 or len(completed.stdout) != expected:
        detail = completed.stderr.decode("utf-8", "replace").strip()[-800:]
        raise AdapterError(
            f"failed to decode anchor {path} to {width}x{height} rgb24: "
            f"exit {completed.returncode}, {len(completed.stdout)} of {expected} bytes. {detail}"
        )
    array = np.frombuffer(completed.stdout, dtype=np.uint8).reshape(height, width, 3)
    return np.ascontiguousarray(array)
