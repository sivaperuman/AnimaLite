"""CPU decode of approved anchor images into raw RGB24 buffers.

Anchors are decoded with the same externally installed FFmpeg that encodes the
output, so the "real execution path" rule holds for input handling too. Frames
are returned as ``numpy`` arrays shaped ``(height, width, 3)``, ``uint8``.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from animalite.errors import AdapterError, CleanupFailed, JobCancelled, JobTimeoutError
from animalite.media.ffmpeg import FFmpegTools
from animalite.proc import ProcessCancelled, run_capture

__all__ = ["decode_image_rgb24"]


def decode_image_rgb24(
    tools: FFmpegTools,
    path: Path,
    *,
    width: int,
    height: int,
    timeout: float = 60.0,
    cancel: Callable[[], bool] | None = None,
) -> NDArray[np.uint8]:
    """Decode one image to RGB24, scaling to ``width`` x ``height`` on the CPU.

    The scaler is pinned (``flags=bicubic``, full-range RGB output) so anchor
    normalization is repeatable across runs (MR-009).

    ``cancel`` is checked inside the decode, not only around it, so a cancel
    request during a slow or stalled decode is acted on rather than waiting out
    the job deadline.
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
        completed = run_capture(argv, timeout=timeout, cancel=cancel)
    except TimeoutError as exc:
        # Classified as a timeout, not an adapter fault: the caller passes the
        # remaining *job* deadline, so expiry here is the deadline firing. The
        # survivor groups ride along: replacing the exception must not discard
        # the cleanup evidence it carries.
        raise JobTimeoutError(
            f"deadline elapsed after {timeout:.3f}s while decoding anchor {path}",
            survivors=getattr(exc, "survivors", ()),
        ) from exc
    except ProcessCancelled as exc:
        raise JobCancelled(
            f"cancelled while decoding anchor {path}: {exc}", survivors=exc.survivors
        ) from exc
    if completed.survivors:
        raise CleanupFailed(
            f"decoding anchor {path} left process group(s) "
            f"{list(completed.survivors)} alive after teardown",
            survivors=completed.survivors,
        )

    expected = width * height * 3
    if completed.returncode != 0 or len(completed.stdout) != expected:
        detail = completed.stderr.decode("utf-8", "replace").strip()[-800:]
        raise AdapterError(
            f"failed to decode anchor {path} to {width}x{height} rgb24: "
            f"exit {completed.returncode}, {len(completed.stdout)} of {expected} bytes. {detail}"
        )
    array = np.frombuffer(completed.stdout, dtype=np.uint8).reshape(height, width, 3)
    return np.ascontiguousarray(array)
