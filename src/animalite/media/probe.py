"""Decode validation of the encoded output before it is published.

Handoff rule 5: "publish only after encode completion and decode validation ...
A partial file is not a successful result."

The probe counts real decoded frames (``-count_frames``) rather than trusting a
container header, and checks geometry, pixel format, frame rate and duration
against the declared :class:`~animalite.contracts.media.OutputSpec`.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from fractions import Fraction
from pathlib import Path

from animalite.contracts.media import OutputSpec
from animalite.contracts.results import DecodeProbe
from animalite.errors import (
    CleanupFailed,
    JobCancelled,
    JobTimeoutError,
    OutputInvalidError,
)
from animalite.media.ffmpeg import FFmpegTools
from animalite.proc import ProcessCancelled, run_capture

__all__ = ["probe_output", "validate_output"]

#: Encoded container timestamps are rational but stored with limited precision;
#: 1 ms is far tighter than a one-delivery-frame (41.7 ms at 24 fps) error.
DURATION_TOLERANCE_SECONDS = 0.001


def probe_output(
    tools: FFmpegTools,
    path: Path,
    *,
    timeout: float = 120.0,
    cancel: Callable[[], bool] | None = None,
) -> DecodeProbe:
    """Decode-count the file and return what the decoder actually reported.

    Supervised and cancellable: the caller passes the remaining *job*
    deadline, so expiry here is the deadline firing and is classified as a
    timeout rather than as invalid output -- the file was never shown to be
    bad, the clock ran out before it could be read.
    """
    tools.require()
    if not path.exists():
        raise OutputInvalidError(f"output file does not exist: {path}")
    argv = [
        tools.ffprobe_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-select_streams",
        "v:0",
        "-count_frames",
        "-show_entries",
        "stream=codec_name,profile,width,height,pix_fmt,avg_frame_rate,nb_read_frames"
        ":format=format_name,duration,size",
        "-of",
        "json",
        str(path),
    ]
    try:
        completed = run_capture(argv, timeout=timeout, cancel=cancel)
    except TimeoutError as exc:
        raise JobTimeoutError(
            f"deadline elapsed after {timeout:.3f}s while decode-counting {path}; "
            f"the probe process group was torn down and nothing was published",
            survivors=getattr(exc, "survivors", ()),
        ) from exc
    except ProcessCancelled as exc:
        raise JobCancelled(
            f"cancelled while decode-counting {path}: {exc}", survivors=exc.survivors
        ) from exc
    if completed.survivors:
        raise CleanupFailed(
            f"probing {path} left process group(s) {list(completed.survivors)} alive "
            "after teardown",
            survivors=completed.survivors,
        )
    if completed.returncode != 0:
        raise OutputInvalidError(
            f"ffprobe exited {completed.returncode} for {path}: "
            f"{completed.stderr.decode('utf-8', 'replace').strip()[-800:]}"
        )
    try:
        payload = json.loads(completed.stdout)
        stream = payload["streams"][0]
        fmt = payload["format"]
    except (json.JSONDecodeError, KeyError, IndexError) as exc:
        raise OutputInvalidError(
            f"ffprobe returned no decodable video stream for {path}: {exc}"
        ) from exc

    return DecodeProbe(
        container_format=str(fmt.get("format_name", "")),
        codec=str(stream.get("codec_name", "")),
        profile=stream.get("profile"),
        width=int(stream["width"]),
        height=int(stream["height"]),
        pixel_format=str(stream.get("pix_fmt", "")),
        counted_frames=int(stream.get("nb_read_frames", 0)),
        avg_frame_rate=str(stream.get("avg_frame_rate", "0/0")),
        duration_seconds=float(fmt.get("duration", 0.0)),
        size_bytes=int(fmt.get("size", 0)),
    )


def validate_output(probe: DecodeProbe, output: OutputSpec) -> list[str]:
    """Return the list of contract violations; empty means the output is valid."""
    problems: list[str] = []

    if (probe.width, probe.height) != (output.width, output.height):
        problems.append(
            f"decoded geometry {probe.width}x{probe.height} != declared "
            f"{output.width}x{output.height}"
        )
    if probe.pixel_format != output.pixel_format:
        problems.append(
            f"decoded pixel format {probe.pixel_format!r} != declared {output.pixel_format!r}"
        )
    if probe.counted_frames != output.delivery_frame_count:
        problems.append(
            f"decoded {probe.counted_frames} delivery frames; the contract requires "
            f"{output.delivery_frame_count}"
        )
    try:
        rate = Fraction(probe.avg_frame_rate)
    except (ValueError, ZeroDivisionError):
        problems.append(f"decoded average frame rate {probe.avg_frame_rate!r} is unreadable")
    else:
        if rate != Fraction(output.cadence.delivery_fps):
            problems.append(
                f"decoded average frame rate {rate} != declared delivery_fps "
                f"{output.cadence.delivery_fps}"
            )
    expected_duration = float(output.duration_seconds)
    if abs(probe.duration_seconds - expected_duration) > DURATION_TOLERANCE_SECONDS:
        problems.append(
            f"decoded duration {probe.duration_seconds:.6f}s != declared "
            f"{expected_duration:.6f}s (tolerance {DURATION_TOLERANCE_SECONDS}s)"
        )
    if probe.size_bytes <= 0:
        problems.append("decoded file reports zero bytes")
    return problems
