"""Child-process lifetime management with process-group cleanup.

Leaf module: it imports nothing from :mod:`animalite.core`, :mod:`animalite.media`
or :mod:`animalite.adapters`. It lives at the top level rather than under
``core`` so :mod:`animalite.media` can manage child processes without importing
the domain layer -- importing ``animalite.core.process`` executes
``animalite/core/__init__.py``, which imports the service, which imports media,
which is a cycle.

Handoff rule 4: "Timeout, cancellation and crashes must clean up the
worker/encoder process tree, release resources and retain diagnostics."

Children are started in their own session (``start_new_session=True``) so the
whole tree can be signalled with ``killpg``. A plain ``Popen.kill()`` would
leave grandchildren -- an FFmpeg filter helper, or a future native worker's
children -- running as orphans.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import select
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
        #: Process-group ids still alive after teardown. Non-empty means an
        #: orphan survived and the caller should say so rather than assume clean.
        self.survivors: list[int] = []
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
        # Captured once: the group id is the identity we own and must sweep,
        # and getpgid() stops working as soon as the leader is reaped.
        self._group_id: int | None = None
        if _POSIX:
            with contextlib.suppress(ProcessLookupError, OSError):
                self._group_id = os.getpgid(self.process.pid)

    @property
    def pid(self) -> int:
        return self.process.pid

    def write(self, data: bytes, deadline: float | None = None) -> None:
        """Write to the child's stdin, bounded by ``deadline`` (monotonic).

        A plain ``stdin.write()`` blocks indefinitely when the child stops
        reading: the pipe buffer fills and the writer sleeps in the kernel, so a
        job deadline checked *before* the call never fires. Measured: a 0.2 s
        deadline against a child that ignored stdin for 3 s returned after
        3.06 s, classified as an encoder error rather than a timeout.

        So the fd is switched to non-blocking and driven with ``select``, which
        makes the deadline real for the one operation that dominates the
        pipeline. Raises :class:`TimeoutError` on expiry; the caller tears the
        process group down.
        """
        if self.process.stdin is None:  # pragma: no cover - configuration error
            raise RuntimeError("process was started without a stdin pipe")
        if deadline is None or not _POSIX:
            try:
                self.process.stdin.write(data)
            except BrokenPipeError as exc:
                raise BrokenPipeError(self._broken_pipe_message()) from exc
            return

        fd = self.process.stdin.fileno()
        self._set_non_blocking(fd)
        view = memoryview(data)
        while view:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"deadline elapsed while writing to {self.argv[0]!r} "
                    f"(pid {self.pid}); {len(view)} of {len(data)} bytes unwritten"
                )
            _, writable, _ = select.select([], [fd], [], min(remaining, 0.25))
            if not writable:
                if self.process.poll() is not None:
                    raise BrokenPipeError(self._broken_pipe_message())
                continue
            try:
                written = os.write(fd, view)
            except BlockingIOError:
                continue
            except BrokenPipeError as exc:
                raise BrokenPipeError(self._broken_pipe_message()) from exc
            view = view[written:]

    def _broken_pipe_message(self) -> str:
        return (
            f"child {self.argv[0]!r} (pid {self.pid}) closed its input before all "
            f"frames were written; exit code {self.process.poll()}"
        )

    @staticmethod
    def _set_non_blocking(fd: int) -> None:
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        if not flags & os.O_NONBLOCK:
            fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    def close_stdin(self) -> None:
        if self.process.stdin is not None and not self.process.stdin.closed:
            with contextlib.suppress(BrokenPipeError, OSError):
                self.process.stdin.close()

    def wait(self, timeout: float | None) -> int:
        """Wait for exit, killing the group and re-raising on timeout."""
        try:
            return self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.terminate_tree()
            raise

    def terminate_tree(self) -> None:
        """SIGTERM the process group, then SIGKILL anything still alive.

        The leader exiting is not the end: a child tool can outlive it and keep
        holding pipes or CPU. So after the leader is reaped the group is
        SIGKILLed unconditionally and probed, and any survivor is reported in
        :attr:`survivors` rather than silently ignored.
        """
        leader_running = self.process.poll() is None
        if leader_running:
            self._signal_group(signal.SIGTERM)
            deadline = time.monotonic() + self.grace_seconds
            while time.monotonic() < deadline and self.process.poll() is None:
                time.sleep(0.02)
            if self.process.poll() is None:
                self._signal_group(signal.SIGKILL)
                with contextlib.suppress(subprocess.TimeoutExpired):
                    self.process.wait(timeout=self.grace_seconds)

        if self._group_id is None:
            return
        # The leader is gone; sweep the group for descendants that outlived it.
        self._signal_group(signal.SIGKILL)
        deadline = time.monotonic() + self.grace_seconds
        while time.monotonic() < deadline:
            if not self._group_alive():
                self.survivors = []
                return
            time.sleep(0.05)
        self.survivors = [self._group_id]

    def _group_alive(self) -> bool:
        """True while any process remains in the owned group."""
        if self._group_id is None or not _POSIX:
            return False
        try:
            os.killpg(self._group_id, 0)
        except ProcessLookupError:
            return False
        except PermissionError:  # pragma: no cover - foreign process in the group
            return True
        return True

    def _signal_group(self, sig: signal.Signals) -> None:
        if not _POSIX:  # pragma: no cover - Windows fallback
            with contextlib.suppress(ProcessLookupError):
                self.process.send_signal(sig)
            return
        group = self._group_id
        if group is None:  # pragma: no cover - defensive
            with contextlib.suppress(ProcessLookupError):
                self.process.send_signal(sig)
            return
        try:
            os.killpg(group, sig)
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
        # Terminate first: closing stdin can itself block on a full pipe when the
        # child has stopped reading, which would defeat the teardown.
        self.terminate_tree()
        self.close_stdin()
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
