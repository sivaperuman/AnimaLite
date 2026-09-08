"""Streaming CPU encode of the delivery frame stream.

Frames are piped into FFmpeg one at a time. Nothing accumulates the whole clip,
so peak memory stays bounded by a handful of frames regardless of clip length
(handoff rule 6).

The encoder writes into an attempt-owned temporary path. Publishing is the
caller's job and only happens after :mod:`animalite.media.probe` confirms the
file decodes with the declared geometry, frame count and duration (handoff
rule 5).
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Iterable
from pathlib import Path

from animalite.contracts.media import OutputSpec
from animalite.contracts.profile import ThreadBudget
from animalite.errors import EncoderError, JobTimeoutError
from animalite.media.ffmpeg import FFmpegTools
from animalite.proc import ManagedProcess
from animalite.resources import apply_thread_environment

__all__ = ["encode_delivery_stream", "encoder_argv"]


def encoder_argv(
    tools: FFmpegTools,
    output: OutputSpec,
    destination: Path,
    threads: int,
) -> list[str]:
    """Build the pinned encoder command line.

    Every output-affecting flag is explicit -- no FFmpeg default is relied on --
    so the same settings can be recorded in the run record and reproduced.
    """
    return [
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
        f"{output.width}x{output.height}",
        "-r",
        str(output.cadence.delivery_fps),
        "-i",
        "-",
        "-an",
        "-sn",
        "-vsync",
        "passthrough",
        "-c:v",
        output.codec,
        "-profile:v",
        output.codec_profile,
        "-level",
        output.codec_level,
        "-preset",
        output.preset,
        "-crf",
        str(output.crf),
        "-pix_fmt",
        output.pixel_format,
        "-color_primaries",
        output.color_primaries,
        "-color_trc",
        output.color_transfer,
        "-colorspace",
        output.color_matrix,
        "-color_range",
        output.color_range,
        "-threads",
        str(threads),
        "-movflags",
        "+faststart",
        "-f",
        output.container,
        str(destination),
    ]


def encode_delivery_stream(
    tools: FFmpegTools,
    frames: Iterable[bytes],
    output: OutputSpec,
    destination: Path,
    *,
    thread_budget: ThreadBudget,
    timeout_seconds: float,
    stderr_path: Path | None = None,
) -> int:
    """Encode ``frames`` into ``destination`` and return the frames written.

    Raises :class:`EncoderError` on any encoder failure. The process group is
    always torn down, including on timeout, so no encoder is left behind.
    """
    tools.require()
    destination.parent.mkdir(parents=True, exist_ok=True)
    frame_bytes = output.width * output.height * 3
    threads = max(1, thread_budget.encoder_threads)
    argv = encoder_argv(tools, output, destination, threads)
    env = apply_thread_environment(thread_budget)

    written = 0
    deadline = time.monotonic() + timeout_seconds
    with ManagedProcess(argv, env=env, stderr_path=stderr_path) as proc:
        try:
            for frame in frames:
                # The deadline is checked once per delivery frame, so it also
                # bounds slow upstream synthesis: the adapter generator is pulled
                # by this loop. Granularity is therefore one frame, not
                # instantaneous -- an adapter that blocks *inside* a single frame
                # is not interrupted here. Package B's out-of-process worker is
                # where a hard bound belongs.
                if time.monotonic() > deadline:
                    raise JobTimeoutError(
                        f"job deadline of {timeout_seconds:.3f}s elapsed after "
                        f"{written} of {output.delivery_frame_count} delivery frames; "
                        "the encoder process group was torn down and no output was "
                        "published"
                    )
                if len(frame) != frame_bytes:
                    raise EncoderError(
                        f"frame {written} has {len(frame)} bytes; expected {frame_bytes} "
                        f"for {output.width}x{output.height} rgb24"
                    )
                proc.write(frame)
                written += 1
            proc.close_stdin()
            code = proc.wait(timeout=max(0.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired as exc:
            raise JobTimeoutError(
                f"the encoder did not exit within the remaining job deadline "
                f"({timeout_seconds:.3f}s total); its process group was killed. "
                f"stderr: {proc.stderr_text()}"
            ) from exc
        except BrokenPipeError as exc:
            proc.wait(timeout=5.0)
            raise EncoderError(
                f"encoder closed its input after {written} frames: {exc}; "
                f"stderr: {proc.stderr_text()}"
            ) from exc

        if code != 0:
            raise EncoderError(
                f"encoder exited {code} after {written} frames; stderr: {proc.stderr_text()}"
            )

    if written != output.delivery_frame_count:
        raise EncoderError(
            f"wrote {written} delivery frames; the output contract requires "
            f"{output.delivery_frame_count}"
        )
    return written
