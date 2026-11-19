"""Structured JSON logging (NFR-013).

Diagnostics go to stderr as one JSON object per line and are mirrored into the
attempt's own log file. Machine-readable command output stays on stdout so
``animalite ... --json`` can be piped safely (handoff rule 10).
"""

from __future__ import annotations

import json
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType
from typing import Any, TextIO

__all__ = ["AttemptLogger", "StructuredLogger", "utc_now"]


def utc_now() -> str:
    """Current UTC time as an ISO-8601 string with a ``Z`` suffix."""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int(time.time() % 1 * 1e6):06d}Z"


class StructuredLogger:
    """Minimal JSON-lines logger. No global logging configuration is touched."""

    def __init__(self, stream: TextIO | None = None, *, enabled: bool = True) -> None:
        self._stream = stream if stream is not None else sys.stderr
        self._enabled = enabled
        self._lock = threading.Lock()

    def emit(self, event: str, **fields: Any) -> None:
        if not self._enabled:
            return
        record = {"ts": utc_now(), "event": event, **fields}
        line = json.dumps(record, sort_keys=True, default=str)
        with self._lock:
            self._stream.write(line + "\n")
            self._stream.flush()


class AttemptLogger:
    """Logger bound to one attempt; writes to the attempt log and to stderr."""

    def __init__(
        self,
        attempt_id: str,
        log_path: Path,
        *,
        console: StructuredLogger | None = None,
    ) -> None:
        self.attempt_id = attempt_id
        self.log_path = log_path
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = log_path.open("a", encoding="utf-8")
        self._console = console
        self._lock = threading.Lock()

    def emit(self, event: str, **fields: Any) -> None:
        record = {"ts": utc_now(), "attempt_id": self.attempt_id, "event": event, **fields}
        line = json.dumps(record, sort_keys=True, default=str)
        with self._lock:
            self._handle.write(line + "\n")
            self._handle.flush()
        if self._console is not None:
            self._console.emit(event, attempt_id=self.attempt_id, **fields)

    @contextmanager
    def stage(self, stage: str, **fields: Any) -> Iterator[None]:
        """Log stage start/end with duration, including on failure."""
        start = time.perf_counter()
        self.emit("stage.start", stage=stage, **fields)
        try:
            yield
        except BaseException as exc:
            self.emit(
                "stage.failed",
                stage=stage,
                duration_seconds=round(time.perf_counter() - start, 6),
                error_type=type(exc).__name__,
                error=str(exc),
                **fields,
            )
            raise
        self.emit(
            "stage.end",
            stage=stage,
            duration_seconds=round(time.perf_counter() - start, 6),
            **fields,
        )

    def close(self) -> None:
        with self._lock:
            if not self._handle.closed:
                self._handle.close()

    def __enter__(self) -> AttemptLogger:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
