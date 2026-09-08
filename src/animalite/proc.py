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
    "TEARDOWN_BUDGET_SECONDS",
    "CaptureResult",
    "ManagedProcess",
    "ProcessCancelled",
    "ProcessFailure",
    "ProcessTimeout",
    "process_alive",
    "run_capture",
    "set_non_blocking",
]

_POSIX = os.name == "posix"

#: Longest a blocking operation may sit in the kernel before re-checking the
#: deadline and the cancel predicate. Small enough that cancellation is
#: observed promptly, large enough not to spin.
_POLL_SECONDS = 0.02

#: Total teardown budget: the whole of SIGTERM, the wait for it, SIGKILL, the
#: reap and the group sweep come out of this one allowance. It used to be a
#: *per-phase* grace, so `terminate_tree()` could spend it several times over --
#: measured, `timeout=0.3, grace=1.0` returned at 1.310 s.
TEARDOWN_BUDGET_SECONDS = 5.0

#: Bounded allowance for collecting the exit status of a process that has
#: already been SIGKILLed, so a killed child is not left as a zombie when the
#: teardown budget is spent. It buys a dead process no time; see the note in
#: :meth:`ManagedProcess.terminate_tree`.
_REAP_AFTER_KILL_SECONDS = 0.5


class ProcessFailure(Exception):
    """A child operation that ended badly, carrying its cleanup evidence.

    An exception cannot return a :class:`CaptureResult`, so survivor groups
    computed during teardown used to be discarded the moment one propagated --
    the very paths (timeout, cancellation) where a leaked process is most
    likely. The evidence rides on the exception instead, and every wrapper is
    responsible for carrying it forward rather than replacing it.
    """

    def __init__(
        self,
        message: str,
        *,
        pid: int | None = None,
        elapsed_seconds: float | None = None,
        stderr_tail: str = "",
        survivors: Sequence[int] = (),
    ) -> None:
        super().__init__(message)
        self.pid = pid
        self.elapsed_seconds = elapsed_seconds
        self.stderr_tail = stderr_tail
        self.survivors = tuple(survivors)


class ProcessTimeout(ProcessFailure, TimeoutError):
    """The absolute deadline expired. Also a :class:`TimeoutError` so existing
    ``except TimeoutError`` callers keep their classification unchanged."""


class ProcessCancelled(ProcessFailure):
    """Raised when a blocking child operation was interrupted by cancellation.

    Distinct from :class:`ProcessTimeout`: the deadline had not expired, an
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
        grace_seconds: float = TEARDOWN_BUDGET_SECONDS,
        cancel: Callable[[], bool] | None = None,
    ) -> None:
        self.argv = list(argv)
        #: Total teardown budget, spent once across TERM, KILL, reap and sweep
        #: *for the whole process lifecycle* -- see :attr:`_teardown_deadline`.
        self.grace_seconds = grace_seconds
        #: Set by the first teardown and reused by every later one. Without it a
        #: timeout path calling terminate_tree() followed by close() from the
        #: context manager spent the budget twice: measured 0.200 s then 0.401 s.
        self._teardown_deadline: float | None = None
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
            f"the owned process group was torn down and nothing was published",
            pid=self.pid,
            stderr_tail=self.stderr_text(limit=2000),
            survivors=tuple(self.survivors),
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
                self.terminate_tree()
                raise ProcessTimeout(
                    f"deadline elapsed while writing to {self.argv[0]!r} "
                    f"(pid {self.pid}); {len(view)} of {len(data)} bytes unwritten",
                    pid=self.pid,
                    stderr_tail=self.stderr_text(limit=2000),
                    survivors=tuple(self.survivors),
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

        ``grace_seconds`` is the **total** teardown budget for this process's
        whole lifecycle, not per phase and not per call. It used to start a fresh
        window per phase, and then a fresh window per call -- a timeout path runs
        ``terminate_tree()`` and the context manager then runs ``close()``, so
        one lifecycle spent the budget twice (measured 0.200 s, then 0.401 s).
        """
        if self._teardown_deadline is None:
            self._teardown_deadline = time.monotonic() + self.grace_seconds
        budget = self._teardown_deadline

        def left() -> float:
            return max(0.0, budget - time.monotonic())

        if self.process.poll() is None:
            self._signal_group(signal.SIGTERM)
            while left() > 0 and self.process.poll() is None:
                time.sleep(min(0.02, left()))
            if self.process.poll() is None:
                self._signal_group(signal.SIGKILL)
                # Reaping after SIGKILL is bookkeeping, not waiting for
                # cooperation: SIGKILL cannot be caught, so `waitpid` returns as
                # soon as the kernel finishes tearing the process down. This is
                # NOT the reap floor that made the deadline non-authoritative --
                # that one let a *still-running* process be reported as a
                # success. Here the process is already dead, and skipping the
                # reap only leaves a zombie behind. Bounded, and not spendable
                # again: a later call finds `poll()` non-None and skips it.
                with contextlib.suppress(subprocess.TimeoutExpired):
                    self.process.wait(timeout=max(left(), _REAP_AFTER_KILL_SECONDS))

        if self._group_id is None:
            return
        # The leader is gone; sweep the group for descendants that outlived it.
        self._signal_group(signal.SIGKILL)
        while True:
            if not self._group_alive():
                # A later call must not erase evidence an earlier one
                # established: the leak happened, whatever the group looks like
                # by the time cleanup runs again.
                if not self.survivors:
                    self.survivors = []
                return
            if left() <= 0:
                break
            time.sleep(min(0.05, left()))
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
    grace_seconds: float = TEARDOWN_BUDGET_SECONDS,
) -> CaptureResult:
    """Run ``argv`` to completion with stdout/stderr captured, under supervision.

    The one supervised "run a tool and read its output" primitive. Anchor
    decoding, output probing and the benchmark's process-cold child all use it,
    so there is no second execution engine with its own cleanup rules --
    ``subprocess.run`` supervises only the direct child, leaving a grandchild
    (an FFmpeg filter helper, a future native worker's child) to outlive the
    timeout as an orphan.

    ``timeout`` is one **absolute** launch-to-completion deadline; the separate
    ``grace_seconds`` teardown budget is spent only after it expires, and is
    never added to it.

    Raises :class:`ProcessTimeout` when the deadline expires and
    :class:`ProcessCancelled` when ``cancel`` fires. Both tear the whole group
    down first and carry the survivor groups on the exception, because a raised
    exception cannot return a :class:`CaptureResult` -- and those are exactly
    the paths where a leaked process is most likely.
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
                raise ProcessTimeout(
                    f"{argv[0]!r} (pid {proc.pid}) did not finish within "
                    f"{timeout:.3f}s; its process group was torn down",
                    pid=proc.pid,
                    elapsed_seconds=time.monotonic() - started,
                    stderr_tail=b"".join(chunks[2]).decode("utf-8", "replace")[-2000:],
                    survivors=tuple(proc.survivors),
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
        # EOF on both pipes is NOT proof that the child exited: a process can
        # close fd 1 and 2 and keep running. Measured with the previous 250 ms
        # reap floor: `timeout=0.15` against a child that closed both pipes and
        # slept 0.20 s returned SUCCESS after 0.225 s, so the declared deadline
        # was not authoritative. Poll first -- an already-exited child is reaped
        # immediately -- and otherwise wait only what is left of the absolute
        # deadline, never a moment more.
        code = proc.process.poll()
        if code is None:
            left = deadline - time.monotonic()
            if left <= 0:
                proc.terminate_tree()
                raise ProcessTimeout(
                    f"{argv[0]!r} (pid {proc.pid}) closed its output but had not "
                    f"exited within {timeout:.3f}s; its process group was torn down",
                    pid=proc.pid,
                    elapsed_seconds=time.monotonic() - started,
                    stderr_tail=b"".join(chunks[2]).decode("utf-8", "replace")[-2000:],
                    survivors=tuple(proc.survivors),
                )
            code = proc.wait(timeout=left)
    except subprocess.TimeoutExpired as exc:
        raise ProcessTimeout(
            f"{argv[0]!r} (pid {proc.pid}) did not exit within {timeout:.3f}s; "
            f"its process group was torn down",
            pid=proc.pid,
            elapsed_seconds=time.monotonic() - started,
            stderr_tail=b"".join(chunks[2]).decode("utf-8", "replace")[-2000:],
            survivors=tuple(proc.survivors),
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
