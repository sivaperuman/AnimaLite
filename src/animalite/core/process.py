"""Child-process lifetime management with process-group cleanup.

Handoff rule 4: "Timeout, cancellation and crashes must clean up the
worker/encoder process tree, release resources and retain diagnostics."

Children are started in their own session (``start_new_session=True``) so the
whole tree can be signalled with ``killpg``. A plain ``Popen.kill()`` would
leave grandchildren -- an FFmpeg filter helper, or a future native worker's
children -- running as orphans.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from types import TracebackType
from typing import IO

__all__ = ["ManagedProcess", "process_alive"]

_POSIX = os.name == "posix"


def process_alive(pid: int) -> bool:
    """True when ``pid`` still exists (best effort, POSIX)."""
    if not _POSIX:  # pragma: no cover - Windows fallback
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class ManagedProcess:
    """A child process whose whole group is cleaned up on exit.

    Used as a context manager so a raised exception, a timeout and a cancel
    all take the same teardown path.
    """

    def __init__(
        self,
        argv: Sequence[str],
        *,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
        stdin: int | None = subprocess.PIPE,
        stderr_path: Path | None = None,
        grace_seconds: float = 5.0,
    ) -> None:
        self.argv = list(argv)
        self.grace_seconds = grace_seconds
        self._stderr_path = stderr_path
        self._stderr_file: IO[bytes] | None = (
            stderr_path.open("wb") if stderr_path is not None else None
        )
        stderr_target: IO[bytes] | int = (
            self._stderr_file if self._stderr_file is not None else subprocess.PIPE
        )
        self.process = subprocess.Popen(  # noqa: S603 - argv list, no shell
            self.argv,
            stdin=stdin,
            stdout=subprocess.DEVNULL,
            stderr=stderr_target,
            env=env,
            cwd=str(cwd) if cwd is not None else None,
            start_new_session=_POSIX,
        )

    @property
    def pid(self) -> int:
        return self.process.pid

    def write(self, data: bytes) -> None:
        """Write to the child's stdin, translating a dead pipe into a clear error."""
        if self.process.stdin is None:  # pragma: no cover - configuration error
            raise RuntimeError("process was started without a stdin pipe")
        try:
            self.process.stdin.write(data)
        except BrokenPipeError as exc:
            raise BrokenPipeError(
                f"child {self.argv[0]!r} (pid {self.pid}) closed its input before all "
                f"frames were written; exit code {self.process.poll()}"
            ) from exc

    def close_stdin(self) -> None:
        if self.process.stdin is not None and not self.process.stdin.closed:
            with contextlib.suppress(BrokenPipeError):
                self.process.stdin.close()

    def wait(self, timeout: float | None) -> int:
        """Wait for exit, killing the group and re-raising on timeout."""
        try:
            return self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.terminate_tree()
            raise

    def terminate_tree(self) -> None:
        """SIGTERM the process group, then SIGKILL anything still alive."""
        if self.process.poll() is not None:
            return
        self._signal_group(signal.SIGTERM)
        deadline = time.monotonic() + self.grace_seconds
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                return
            time.sleep(0.02)
        self._signal_group(signal.SIGKILL)
        # pragma: no cover - only reached if the kernel refuses SIGKILL
        with contextlib.suppress(subprocess.TimeoutExpired):
            self.process.wait(timeout=self.grace_seconds)

    def _signal_group(self, sig: signal.Signals) -> None:
        if not _POSIX:  # pragma: no cover - Windows fallback
            self.process.send_signal(sig)
            return
        try:
            os.killpg(os.getpgid(self.process.pid), sig)
        except (ProcessLookupError, PermissionError):
            with contextlib.suppress(ProcessLookupError):
                self.process.send_signal(sig)

    def stderr_text(self, limit: int = 8000) -> str:
        """Return captured stderr, from the file when one was configured."""
        if self._stderr_path is not None:
            try:
                data = self._stderr_path.read_bytes()
            except OSError:  # pragma: no cover - unreadable diagnostics file
                return ""
            return data.decode("utf-8", "replace")[-limit:]
        if self.process.stderr is None:
            return ""
        return self.process.stderr.read().decode("utf-8", "replace")[-limit:]

    def close(self) -> None:
        self.close_stdin()
        self.terminate_tree()
        for stream in (self.process.stdout, self.process.stderr):
            if stream is not None and not stream.closed:
                stream.close()
        if self._stderr_file is not None and not self._stderr_file.closed:
            self._stderr_file.close()

    def __enter__(self) -> ManagedProcess:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


if not _POSIX and sys.platform != "win32":  # pragma: no cover - defensive
    raise RuntimeError("unsupported platform for ManagedProcess")
