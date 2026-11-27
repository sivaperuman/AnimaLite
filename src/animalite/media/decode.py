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

from animalite.contracts.profile import ThreadBudget
from animalite.errors import AdapterError, CleanupFailed, JobCancelled, JobTimeoutError
from animalite.media.ffmpeg import FFmpegTools
from animalite.proc import ProcessCancelled, run_capture
from animalite.resources import apply_thread_environment

__all__ = ["decode_image_rgb24"]


def decode_image_rgb24(
    tools: FFmpegTools,
    path: Path,
    *,
    width: int,
    height: int,
    timeout: float,
    cancel: Callable[[], bool] | None = None,
    thread_budget: ThreadBudget | None = None,
) -> NDArray[np.uint8]:
    """Decode one image to RGB24, scaling to ``width`` x ``height`` on the CPU.

    The scaler is pinned (``flags=bicubic``, full-range RGB output) so anchor
    normalization is repeatable across runs (MR-009).

    ``cancel`` is checked inside the decode, not only around it, so a cancel
    request during a slow or stalled decode is acted on rather than waiting out
    the job deadline.

    ``timeout`` has no default on purpose. It is the caller's *remaining job
    budget*, and a default turned it into a private 60 s allowance that each
    anchor decode and each generated-frame decode could spend after the job
    deadline had already passed. Every call site now states its bound.
    ``thread_budget`` pins the decoder's threads so intermediate image I/O is
    inside the same envelope as the rest of the pipeline.
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
    if thread_budget is not None:
        # Input side here, because the expensive part of a decode is the image
        # decoder, not the rawvideo output. `-filter_threads` bounds the scaler,
        # which is a separate pool and would otherwise size itself to the host.
        threads = str(max(1, thread_budget.encoder_threads))
        argv[1:1] = ["-threads", threads, "-filter_threads", threads]
    try:
        completed = run_capture(
            argv,
            timeout=timeout,
            cancel=cancel,
            env=apply_thread_environment(thread_budget) if thread_budget else None,
        )
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
