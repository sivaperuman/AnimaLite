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
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import IO

__all__ = [
    "CaptureResult",
    "ManagedProcess",
    "ProcessCancelled",
    "process_alive",
    "run_capture",
    "set_non_blocking",
]

_POSIX = os.name == "posix"

#: Longest a blocking operation may sit in the kernel before re-checking the
#: deadline and the cancel predicate. Small enough that cancellation is
#: observed promptly, large enough not to spin.
_POLL_SECONDS = 0.02

#: Floor for the final exit-status wait once the child's pipes are at EOF.
#: Collecting the status of a process that has already finished is not work the
#: deadline should be able to fail.
_REAP_SECONDS = 0.25


class ProcessCancelled(Exception):
    """Raised when a blocking child operation was interrupted by cancellation.

    Distinct from :class:`TimeoutError`: the deadline had not expired, an
    external cancel request arrived. The caller maps it to a ``cancelled``
    attempt, never to a timeout or an encoder fault.
    """


@dataclass(frozen=True)
class CaptureResult:
    """Outcome of a supervised child run whose stdout/stderr were captured."""

    returncode: int
    stdout: bytes
    stderr: bytes
    pid: int
    elapsed_seconds: float
    #: Process-group ids still alive after teardown. Non-empty means an orphan
    #: survived; the caller reports it rather than assuming a clean exit.
    survivors: tuple[int, ...] = ()


def set_non_blocking(fd: int) -> None:
    """Put ``fd`` in non-blocking mode so ``select`` can bound reads and writes."""
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    if not flags & os.O_NONBLOCK:
        fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)


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
        stdout: int = subprocess.DEVNULL,
        stderr_path: Path | None = None,
        grace_seconds: float = 5.0,
        cancel: Callable[[], bool] | None = None,
    ) -> None:
        self.argv = list(argv)
        self.grace_seconds = grace_seconds
        #: Checked inside every blocking operation. Without it a cancel request
        #: cannot reach a write parked in the kernel or a wait on a stalled
        #: child: measured, a cancel at 0.30s was only observed at 3.01s, when
        #: the child happened to exit on its own.
        self._cancel = cancel
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
            stdout=stdout,
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

    def cancelled(self) -> bool:
        """True when the owner has asked for this work to stop."""
        return self._cancel is not None and self._cancel()

    def raise_if_cancelled(self, during: str) -> None:
        """Tear the group down and raise when cancellation has been requested."""
        if not self.cancelled():
            return
        self.terminate_tree()
        raise ProcessCancelled(
            f"cancellation requested while {during} {self.argv[0]!r} (pid {self.pid}); "
            f"the owned process group was torn down and nothing was published"
        )

    def write(self, data: bytes, deadline: float | None = None) -> None:
        """Write to the child's stdin, bounded by ``deadline`` (monotonic).

        A plain ``stdin.write()`` blocks indefinitely when the child stops
        reading: the pipe buffer fills and the writer sleeps in the kernel, so a
        job deadline checked *before* the call never fires. Measured: a 0.2 s
        deadline against a child that ignored stdin for 3 s returned after
        3.06 s, classified as an encoder error rather than a timeout.

        So the fd is switched to non-blocking and driven with ``select``, which
        makes both the deadline and cancellation real for the one operation that
        dominates the pipeline. Raises :class:`TimeoutError` on expiry and
        :class:`ProcessCancelled` on cancellation; the caller tears the process
        group down.

        The bounded path is taken whenever there is *anything* to react to -- a
        deadline or a cancel predicate -- because an unbounded ``write`` is
        exactly what made cancellation unobservable.
        """
        if self.process.stdin is None:  # pragma: no cover - configuration error
            raise RuntimeError("process was started without a stdin pipe")
        if (deadline is None and self._cancel is None) or not _POSIX:
            try:
                self.process.stdin.write(data)
            except BrokenPipeError as exc:
                raise BrokenPipeError(self._broken_pipe_message()) from exc
            return

        fd = self.process.stdin.fileno()
        set_non_blocking(fd)
        view = memoryview(data)
        while view:
            self.raise_if_cancelled(f"writing {len(view)} of {len(data)} bytes to")
            remaining = _POLL_SECONDS if deadline is None else deadline - time.monotonic()
            if deadline is not None and remaining <= 0:
                raise TimeoutError(
                    f"deadline elapsed while writing to {self.argv[0]!r} "
                    f"(pid {self.pid}); {len(view)} of {len(data)} bytes unwritten"
                )
            _, writable, _ = select.select([], [fd], [], min(remaining, _POLL_SECONDS))
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

    def close_stdin(self) -> None:
        if self.process.stdin is not None and not self.process.stdin.closed:
            with contextlib.suppress(BrokenPipeError, OSError):
                self.process.stdin.close()

    def wait(self, timeout: float | None) -> int:
        """Wait for exit, killing the group on timeout or cancellation.

        Polled rather than a single blocking ``Popen.wait`` so a cancel arriving
        mid-wait is acted on now instead of whenever the child happens to
        finish. ``subprocess.TimeoutExpired`` is still what a timeout raises, so
        existing callers keep their classification.
        """
        if self._cancel is None:
            try:
                return self.process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.terminate_tree()
                raise
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            self.raise_if_cancelled("waiting for")
            code = self.process.poll()
            if code is not None:
                return code
            if deadline is not None and time.monotonic() >= deadline:
                self.terminate_tree()
                raise subprocess.TimeoutExpired(self.argv, timeout or 0.0)
            time.sleep(_POLL_SECONDS)

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


def run_capture(
    argv: Sequence[str],
    *,
    timeout: float,
    cancel: Callable[[], bool] | None = None,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    stdin_path: Path | None = None,
    grace_seconds: float = 5.0,
) -> CaptureResult:
    """Run ``argv`` to completion with stdout/stderr captured, under supervision.

    The one supervised "run a tool and read its output" primitive. Anchor
    decoding, output probing and the benchmark's process-cold child all use it,
    so there is no second execution engine with its own cleanup rules --
    ``subprocess.run`` supervises only the direct child, leaving a grandchild
    (an FFmpeg filter helper, a future native worker's child) to outlive the
    timeout as an orphan.

    Raises :class:`TimeoutError` when ``timeout`` expires and
    :class:`ProcessCancelled` when ``cancel`` fires. Both tear the whole group
    down first, and any survivor is reported in
    :attr:`CaptureResult.survivors` rather than assumed away.
    """
    started = time.monotonic()
    deadline = started + timeout
    stdin_file: IO[bytes] | None = None
    if stdin_path is not None:
        stdin_file = stdin_path.open("rb")
    try:
        proc = ManagedProcess(
            argv,
            env=env,
            cwd=cwd,
            stdin=stdin_file.fileno() if stdin_file is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            grace_seconds=grace_seconds,
            cancel=cancel,
        )
    finally:
        if stdin_file is not None:
            stdin_file.close()

    chunks: dict[int, list[bytes]] = {1: [], 2: []}
    try:
        streams = {
            stream.fileno(): (index, stream)
            for index, stream in ((1, proc.process.stdout), (2, proc.process.stderr))
            if stream is not None
        }
        for fd in streams:
            set_non_blocking(fd)
        open_fds = set(streams)
        while open_fds:
            proc.raise_if_cancelled("reading the output of")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                proc.terminate_tree()
                raise TimeoutError(
                    f"{argv[0]!r} (pid {proc.pid}) did not finish within "
                    f"{timeout:.3f}s; its process group was torn down"
                )
            readable, _, _ = select.select(list(open_fds), [], [], min(remaining, _POLL_SECONDS))
            for fd in readable:
                index, _stream = streams[fd]
                try:
                    data = os.read(fd, 65536)
                except BlockingIOError:  # pragma: no cover - transient
                    continue
                except OSError:  # pragma: no cover - fd torn down under us
                    open_fds.discard(fd)
                    continue
                if data:
                    chunks[index].append(data)
                else:
                    open_fds.discard(fd)
        # Both pipes are at EOF, so the child has closed them; the remaining
        # wait is only to collect the exit status. A small floor keeps a child
        # that finished exactly as the deadline expired from being reported as a
        # timeout -- it is reaping an already-finished process, not more work.
        code = proc.wait(timeout=max(_REAP_SECONDS, deadline - time.monotonic()))
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(
            f"{argv[0]!r} (pid {proc.pid}) did not exit within {timeout:.3f}s; "
            f"its process group was torn down"
        ) from exc
    finally:
        proc.close()
        survivors = tuple(proc.survivors)

    return CaptureResult(
        returncode=code,
        stdout=b"".join(chunks[1]),
        stderr=b"".join(chunks[2]),
        pid=proc.pid,
        elapsed_seconds=time.monotonic() - started,
        survivors=survivors,
    )


if not _POSIX and sys.platform != "win32":  # pragma: no cover - defensive
    raise RuntimeError("unsupported platform for ManagedProcess")
