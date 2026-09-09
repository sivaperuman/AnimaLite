"""Single-frame image encoding through the installed FFmpeg.

Used by the fixture generator to write synthetic anchors and by the RIFE
adapter to hand normalized anchors to a runtime whose interface is file-based.
Keeping it here means there is exactly one PNG writer and it goes through the
same external tool as the rest of the media path.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from animalite.contracts.profile import ThreadBudget
from animalite.errors import AdapterError, CleanupFailed, JobCancelled, JobTimeoutError
from animalite.media.ffmpeg import FFmpegTools
from animalite.proc import ProcessCancelled, ProcessTimeout, run_capture
from animalite.resources import apply_thread_environment

__all__ = ["write_png_rgb24"]


def write_png_rgb24(
    tools: FFmpegTools,
    frame: NDArray[np.uint8],
    destination: Path,
    *,
    timeout: float,
    cancel: Callable[[], bool] | None = None,
    thread_budget: ThreadBudget | None = None,
) -> Path:
    """Write one RGB24 frame to a PNG losslessly.

    ``-compression_level 9 -pred none`` keeps the output byte-reproducible for a
    given frame, which is what makes the fixture generator's hashes stable.

    ``timeout`` is the caller's *remaining job budget*, not a private allowance:
    a per-call default let anchor writes and frame decodes each spend their own
    60 s while the job deadline had already passed. ``thread_budget`` pins the
    encoder threads so intermediate image I/O counts against the same envelope
    as everything else.
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
    if thread_budget is not None:
        # On the *output* side: an option before `-i` binds to the input
        # decoder, which for rawvideo does nothing, and would have left the PNG
        # encoder unbounded. This mirrors where the delivery encoder puts it.
        argv[-1:-1] = ["-threads", str(max(1, thread_budget.encoder_threads))]
    destination.parent.mkdir(parents=True, exist_ok=True)
    raw = frame.tobytes()
    stdin_path = destination.parent / f".{destination.name}.raw"
    stdin_path.write_bytes(raw)
    try:
        completed = run_capture(
            argv,
            timeout=timeout,
            cancel=cancel,
            env=apply_thread_environment(thread_budget) if thread_budget else None,
            stdin_path=stdin_path,
        )
    except ProcessTimeout as exc:
        raise JobTimeoutError(
            f"the job deadline expired while writing {destination}",
            survivors=getattr(exc, "survivors", ()),
        ) from exc
    except ProcessCancelled as exc:
        raise JobCancelled(
            f"cancelled while writing {destination}: {exc}",
            survivors=getattr(exc, "survivors", ()),
        ) from exc
    finally:
        stdin_path.unlink(missing_ok=True)
    if completed.survivors:
        raise CleanupFailed(
            f"writing {destination} left process group(s) {list(completed.survivors)} alive",
            survivors=completed.survivors,
        )
    if completed.returncode != 0 or not destination.exists():
        raise AdapterError(
            f"failed to write {destination}: exit {completed.returncode}; "
            f"{completed.stderr.decode('utf-8', 'replace').strip()[-500:]}"
        )
    return destination
