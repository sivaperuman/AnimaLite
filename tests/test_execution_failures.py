"""Failure cleanup, timeouts, cancellation and retry semantics.

Handoff rules 4 and 5: a timeout, cancellation or crash must clean up the
process tree, retain diagnostics and never publish a partial encode as
successful output; a retry creates a new attempt linked to its parent.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest

from animalite.adapters.fixture import FIXTURE_PROFILE, FixtureAdapter
from animalite.adapters.registry import Registry
from animalite.contracts.enums import FailureCategory, JobState
from animalite.contracts.media import P_L_FINAL_OUTPUT, PREVIEW_OUTPUT
from animalite.core.attempts import AttemptStore
from animalite.core.service import OUTPUT_FILENAME, LocalExecutionService
from animalite.errors import AttemptConflictError
from animalite.media.ffmpeg import FFmpegTools
from animalite.proc import ManagedProcess, process_alive
from tests.conftest import make_request, require_media

pytestmark = pytest.mark.media


class ExplodingAdapter(FixtureAdapter):
    """Fails part-way through synthesis, after the encoder has started."""

    key = "exploding"

    def synthesize(self, context):
        for index, frame in enumerate(super().synthesize(context)):
            if index == 10:
                raise RuntimeError("simulated adapter crash mid-synthesis")
            yield frame


class ShortAdapter(FixtureAdapter):
    """Stops early, so the encoder receives fewer frames than the contract needs."""

    key = "short"

    def synthesize(self, context):
        for index, frame in enumerate(super().synthesize(context)):
            if index >= 5:
                return
            yield frame


class WrongGeometryAdapter(FixtureAdapter):
    key = "wrong-geometry"

    def synthesize(self, context):
        for _ in range(context.output.animation_frame_count):
            yield np.zeros((10, 10, 3), dtype=np.uint8)


class SlowAdapter(FixtureAdapter):
    """Sleeps between frames so a short job timeout is reached deterministically."""

    key = "slow"

    def synthesize(self, context):
        for frame in super().synthesize(context):
            time.sleep(0.4)
            yield frame


def _service_with(adapter, tmp_path: Path, profile_id: str) -> LocalExecutionService:
    registry = Registry()
    registry.register_adapter(adapter)
    registry.register_profile(
        FIXTURE_PROFILE.model_copy(update={"profile_id": profile_id, "adapter_key": adapter.key})
    )
    return LocalExecutionService(tmp_path / "ws", registry=registry, tools=FFmpegTools.discover())


def _assert_no_published_output(record):
    assert record.output is None
    output_dir = Path(record.attempt_dir) / "output"
    published = list(output_dir.glob("*")) if output_dir.exists() else []
    assert published == [], f"a failed attempt published {published}"


def test_an_adapter_crash_leaves_no_successful_output_and_retains_diagnostics(
    tmp_path, fixture_anchors
):
    service = _service_with(ExplodingAdapter(), tmp_path, "exploding-profile")
    record = service.render_blocking(make_request(fixture_anchors, profile_id="exploding-profile"))

    assert record.state is JobState.FAILED
    assert record.failure is not None
    assert "simulated adapter crash" in record.failure.message
    _assert_no_published_output(record)

    diagnostics = Path(record.failure.diagnostics_path or "")
    assert diagnostics.is_dir()
    # A partial encode is retained under a name that cannot be mistaken for output.
    retained = {p.name for p in diagnostics.iterdir()}
    assert retained, "diagnostics directory is empty"
    assert OUTPUT_FILENAME not in retained
    assert (Path(record.attempt_dir) / "logs" / "attempt.jsonl").is_file()


def test_a_short_adapter_stream_fails_rather_than_publishing_a_short_clip(
    tmp_path, fixture_anchors
):
    service = _service_with(ShortAdapter(), tmp_path, "short-profile")
    record = service.render_blocking(make_request(fixture_anchors, profile_id="short-profile"))
    assert record.state is JobState.FAILED
    assert record.failure is not None
    assert record.failure.category is FailureCategory.ADAPTER_ERROR
    _assert_no_published_output(record)


def test_wrong_frame_geometry_is_rejected_before_encoding(tmp_path, fixture_anchors):
    service = _service_with(WrongGeometryAdapter(), tmp_path, "wrong-geometry-profile")
    record = service.render_blocking(
        make_request(fixture_anchors, profile_id="wrong-geometry-profile")
    )
    assert record.state is JobState.FAILED
    assert record.failure is not None
    assert "expected (360, 640, 3)" in record.failure.message
    _assert_no_published_output(record)


def test_a_job_timeout_kills_the_encoder_and_leaves_no_orphan(tmp_path, fixture_anchors):
    service = _service_with(SlowAdapter(), tmp_path, "slow-profile")
    request = make_request(fixture_anchors, profile_id="slow-profile", timeout_seconds=1.0)
    record = service.render_blocking(request)

    assert record.state is JobState.FAILED
    assert record.failure is not None
    assert record.failure.category is FailureCategory.TIMEOUT
    _assert_no_published_output(record)

    # No ffmpeg child of this process survives the teardown.
    import subprocess

    children = subprocess.run(
        ["pgrep", "-P", str(__import__("os").getpid())],
        capture_output=True,
        text=True,
        check=False,
    )
    surviving = [pid for pid in children.stdout.split() if pid.strip()]
    assert not surviving, f"orphan child processes remain: {surviving}"


def test_cancellation_produces_a_cancelled_attempt_with_no_output(tmp_path, fixture_anchors):
    service = _service_with(SlowAdapter(), tmp_path, "cancel-profile")
    job_id = service.submit(make_request(fixture_anchors, profile_id="cancel-profile"))
    time.sleep(0.6)
    result = service.cancel(job_id)
    assert result.accepted
    assert result.safe_cancellation_supported
    assert "no partial output is published" in result.message.lower()

    record = service.collect(job_id)
    assert record.state is JobState.CANCELLED
    assert record.failure is not None
    assert record.failure.category is FailureCategory.CANCELLED
    _assert_no_published_output(record)


def test_cancelling_a_finished_job_is_reported_honestly(tmp_path, fixture_anchors):
    service = LocalExecutionService(tmp_path / "ws", tools=FFmpegTools.discover())
    job_id = service.submit(make_request(fixture_anchors))
    service.collect(job_id)
    result = service.cancel(job_id)
    assert not result.accepted
    assert "already succeeded" in result.message


def test_a_retry_creates_a_new_attempt_and_preserves_the_parent(tmp_path, fixture_anchors):
    service = _service_with(ExplodingAdapter(), tmp_path, "exploding-profile")
    first = service.render_blocking(
        make_request(fixture_anchors, profile_id="exploding-profile", request_id="r1")
    )
    assert first.state is JobState.FAILED

    # Retry through a working profile, linked to the failed parent.
    working = LocalExecutionService(tmp_path / "ws", tools=FFmpegTools.discover())
    second = working.render_blocking(
        make_request(fixture_anchors, request_id="r1-retry", parent_attempt_id=first.attempt_id)
    )
    assert second.state is JobState.SUCCEEDED
    assert second.attempt_id != first.attempt_id
    assert second.parent_attempt_id == first.attempt_id
    assert second.retry_index == first.retry_index + 1

    # The original attempt record and its diagnostics are untouched.
    reloaded = AttemptStore(tmp_path / "ws").load(first.attempt_id)
    assert reloaded.state is JobState.FAILED
    assert reloaded.output is None
    assert reloaded.finished_at == first.finished_at
    _assert_no_published_output(reloaded)


def test_a_terminal_attempt_record_is_immutable(tmp_path, fixture_anchors):
    service = LocalExecutionService(tmp_path / "ws", tools=FFmpegTools.discover())
    record = service.render_blocking(make_request(fixture_anchors))
    store = AttemptStore(tmp_path / "ws")
    with pytest.raises(AttemptConflictError, match="already terminal"):
        store.save(record)


def test_an_attempt_directory_is_never_reused(tmp_path):
    store = AttemptStore(tmp_path / "ws")
    store.allocate("att-fixed")
    with pytest.raises(AttemptConflictError, match="immutable"):
        store.allocate("att-fixed")


def test_publishing_twice_is_refused(tmp_path):
    store = AttemptStore(tmp_path / "ws")
    dirs = store.allocate("att-publish")
    (dirs.work / "a.mp4").write_bytes(b"first")
    dirs.publish(dirs.work / "a.mp4", "output.mp4")
    (dirs.work / "a.mp4").write_bytes(b"second")
    with pytest.raises(AttemptConflictError, match="refusing to overwrite"):
        dirs.publish(dirs.work / "a.mp4", "output.mp4")


def test_a_managed_process_group_is_torn_down_on_exit():
    require_media()
    with ManagedProcess(["sh", "-c", "sleep 30 & wait"], stdin=None) as proc:
        pid = proc.pid
        time.sleep(0.2)
        assert process_alive(pid)
    deadline = time.time() + 10
    while time.time() < deadline and process_alive(pid):
        time.sleep(0.05)
    assert not process_alive(pid)


def test_only_one_render_runs_at_a_time(tmp_path, fixture_anchors):
    """P-L policy: one render job at a time on the low-spec host."""
    service = _service_with(SlowAdapter(), tmp_path, "serial-profile")
    request_a = make_request(fixture_anchors, profile_id="serial-profile", request_id="a")
    request_b = make_request(fixture_anchors, profile_id="serial-profile", request_id="b")
    job_a = service.submit(request_a)
    job_b = service.submit(request_b)
    time.sleep(0.8)
    states = {service.status(job_a).state, service.status(job_b).state}
    assert JobState.QUEUED in states, f"both jobs ran concurrently: {states}"
    service.cancel(job_a)
    service.cancel(job_b)
    for job in (job_a, job_b):
        service.wait(job, timeout=60)


def test_a_validation_rejection_is_recorded_as_a_failed_attempt(tmp_path, fixture_anchors):
    service = LocalExecutionService(tmp_path / "ws", tools=FFmpegTools.discover())
    request = make_request(fixture_anchors, controls={"unknown_control": 1})
    record = service.render_blocking(request)
    assert record.state is JobState.FAILED
    assert record.failure is not None
    assert record.failure.category is FailureCategory.VALIDATION_REJECTED
    assert "VAL-CONTROL-UNSUPPORTED" in record.failure.validation_codes
    _assert_no_published_output(record)


# --- R4 regressions: deadlines and teardown across blocking I/O ---------------


def _stall_script(tmp_path: Path, seconds: float = 30.0) -> Path:
    """A child that never reads stdin, so a writer fills the pipe and blocks."""
    script = tmp_path / "stall.py"
    script.write_text(f"import time\ntime.sleep({seconds})\n")
    return script


def test_the_deadline_bounds_a_write_to_a_child_that_never_reads(tmp_path):
    """The pipeline's dominant operation must be interruptible.

    A deadline checked before a blocking `stdin.write()` never fires once the
    pipe buffer fills: measured 3.06s against a 0.2s deadline, misclassified as
    an encoder error.
    """
    from unittest.mock import patch

    from animalite.contracts.profile import ThreadBudget
    from animalite.errors import JobTimeoutError
    from animalite.media import encode as encode_module

    output = P_L_FINAL_OUTPUT
    frame = b"\x00" * (output.width * output.height * 3)

    def frames():
        for _ in range(output.delivery_frame_count):
            yield frame

    argv = [sys.executable, str(_stall_script(tmp_path))]
    with patch.object(encode_module, "encoder_argv", lambda *a, **k: argv):
        started = time.monotonic()
        with pytest.raises(JobTimeoutError, match="deadline"):
            encode_module.encode_delivery_stream(
                FFmpegTools.discover(),
                frames(),
                output,
                tmp_path / "out.mp4",
                thread_budget=ThreadBudget(total_threads=4),
                timeout_seconds=0.2,
            )
        elapsed = time.monotonic() - started
    assert elapsed < 2.0, f"deadline of 0.2s took {elapsed:.3f}s to fire"
    # "absent OR size >= 0" is true of every normal file and proved nothing.
    assert not (tmp_path / "out.mp4").exists(), (
        "a file was left at the publish path after a deadline breach"
    )


def test_a_descendant_that_outlives_its_leader_is_killed(tmp_path):
    """Killing only the leader leaves grandchildren holding resources."""
    script = tmp_path / "spawner.py"
    marker = tmp_path / "descendant.pid"
    script.write_text(
        "import os, subprocess, sys, time\n"
        f"child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"open({str(marker)!r}, 'w').write(str(child.pid))\n"
        "time.sleep(60)\n"
    )
    with ManagedProcess([sys.executable, str(script)], stdin=None) as proc:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not marker.exists():
            time.sleep(0.05)
        assert marker.exists(), "the child never spawned its descendant"
        descendant = int(marker.read_text())
        assert process_alive(descendant)
        leader = proc.pid

    for pid in (leader, descendant):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and process_alive(pid):
            time.sleep(0.05)
        assert not process_alive(pid), f"pid {pid} survived teardown"


def test_teardown_reports_survivors_rather_than_assuming_success(tmp_path):
    """`survivors` must be empty only when the group really is gone."""
    with ManagedProcess([sys.executable, "-c", "import time; time.sleep(30)"], stdin=None) as proc:
        time.sleep(0.2)
    assert proc.survivors == [], f"teardown left survivors: {proc.survivors}"


def test_anchor_decode_is_bounded_by_the_remaining_job_deadline(tmp_path, fixture_anchors):
    """Anchor decode used its own 60s timeout regardless of the job budget."""
    service = LocalExecutionService(tmp_path / "ws", tools=FFmpegTools.discover())
    record = service.render_blocking(make_request(fixture_anchors, timeout_seconds=0.001))
    assert record.state is JobState.FAILED
    assert record.failure is not None
    assert record.failure.category is FailureCategory.TIMEOUT
    _assert_no_published_output(record)


# --- R4 regression: cancellation must reach the blocking native operations ----


def _handshake_script(tmp_path: Path, seconds: float = 8.0) -> Path:
    """A finite child that announces itself and then never reads stdin.

    It exits on its own after `seconds`, so a test that ends only when the child
    ends is visibly distinguishable from one ended by cancellation.
    """
    script = tmp_path / "handshake_stall.py"
    script.write_text(
        "import sys, time\n"
        "sys.stderr.write('READY\\n')\n"
        "sys.stderr.flush()\n"
        f"time.sleep({seconds})\n"
    )
    return script


def test_cancellation_interrupts_a_pipe_write_rather_than_waiting_out_the_child(tmp_path):
    """R4: cancel must reach inside the blocking write, not merely around it.

    Measured before the fix: with a 600s job deadline and a child that ignored
    stdin for 3s, a cancel at 0.30s was only observed at 3.013s -- when the
    child exited on its own. Termination has to be driven by the cancel.
    """
    import threading

    from animalite.proc import ManagedProcess, ProcessCancelled

    child_seconds = 8.0
    cancel = threading.Event()
    proc = ManagedProcess(
        [sys.executable, str(_handshake_script(tmp_path, child_seconds))],
        stderr_path=tmp_path / "child.err",
        cancel=cancel.is_set,
    )
    try:
        # Handshake: wait until the child has actually started before cancelling,
        # so the write is genuinely in progress rather than racing startup.
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if b"READY" in (tmp_path / "child.err").read_bytes():
                break
            time.sleep(0.01)
        else:  # pragma: no cover - the child failed to start
            pytest.fail("the child never signalled READY")

        threading.Timer(0.2, cancel.set).start()
        started = time.monotonic()
        with pytest.raises(ProcessCancelled, match="cancellation requested"):
            # Far larger than any pipe buffer, so the write must block.
            proc.write(b"x" * (8 * 1024 * 1024), deadline=time.monotonic() + 600.0)
        elapsed = time.monotonic() - started
    finally:
        proc.close()

    assert elapsed < child_seconds / 2, (
        f"the write returned after {elapsed:.3f}s; with the child alive for "
        f"{child_seconds:.1f}s that is the child exiting, not cancellation"
    )
    assert not proc.survivors, f"cancellation left process group(s) {proc.survivors} alive"


def test_cancellation_interrupts_a_supervised_capture(tmp_path):
    """R4: the same must hold for decode/probe, which read a child's output."""
    import threading

    from animalite.proc import ProcessCancelled, run_capture

    child_seconds = 8.0
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    started = time.monotonic()
    with pytest.raises(ProcessCancelled, match="cancellation requested"):
        run_capture(
            [sys.executable, "-c", f"import time; time.sleep({child_seconds})"],
            timeout=600.0,
            cancel=cancel.is_set,
        )
    elapsed = time.monotonic() - started
    assert elapsed < child_seconds / 2, (
        f"the capture returned after {elapsed:.3f}s, which is the child exiting "
        "rather than cancellation taking effect"
    )


def test_a_cancelled_encode_is_a_cancelled_attempt_and_publishes_nothing(tmp_path):
    """R4: cancellation during encode is `cancelled`, never an encoder fault."""
    import threading
    from unittest.mock import patch

    from animalite.contracts.profile import ThreadBudget
    from animalite.errors import JobCancelled
    from animalite.media import encode as encode_module

    output = P_L_FINAL_OUTPUT
    frame = b"\x00" * (output.width * output.height * 3)

    def frames():
        for _ in range(output.delivery_frame_count):
            yield frame

    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    argv = [sys.executable, str(_stall_script(tmp_path, seconds=8.0))]
    destination = tmp_path / "cancelled.mp4"
    with patch.object(encode_module, "encoder_argv", lambda *a, **k: argv):
        started = time.monotonic()
        with pytest.raises(JobCancelled, match="cancelled"):
            encode_module.encode_delivery_stream(
                FFmpegTools.discover(),
                frames(),
                output,
                destination,
                thread_budget=ThreadBudget(total_threads=4),
                timeout_seconds=600.0,
                cancel=cancel.is_set,
            )
        elapsed = time.monotonic() - started

    assert elapsed < 4.0, f"cancellation took {elapsed:.3f}s against a live child"
    assert not destination.exists(), "a partial file was left at the publish path"


def test_a_probe_deadline_is_classified_as_a_timeout_not_invalid_output(tmp_path):
    """R4: the clock running out during probing is the deadline, not a bad file.

    Calling it `output_invalid` would claim the file was shown to be bad; it was
    never read.
    """
    from unittest.mock import patch

    from animalite.errors import JobTimeoutError
    from animalite.media import probe as probe_module

    target = tmp_path / "clip.mp4"
    target.write_bytes(b"\x00" * 1024)
    with patch.object(probe_module, "run_capture") as capture:
        capture.side_effect = TimeoutError("probe exceeded its deadline")
        with pytest.raises(JobTimeoutError, match="deadline elapsed"):
            probe_module.probe_output(FFmpegTools.discover(), target, timeout=0.2)


# --- R4 round 3: one absolute deadline, one total teardown budget ------------


def test_closing_both_pipes_does_not_buy_a_process_extra_time(tmp_path):
    """R4.1: EOF is not proof of exit, and must not extend the deadline.

    A 250 ms reap floor was added so a child finishing exactly on the deadline
    would not be called a timeout. But a process can close fd 1 and 2 and keep
    running: measured, `timeout=0.15` against a child that closed both pipes and
    slept 0.20 s returned SUCCESS after 0.225 s. The declared deadline has to be
    authoritative.
    """
    from animalite.proc import ProcessTimeout, run_capture

    script = tmp_path / "close_and_live.py"
    script.write_text("import os, time\nos.close(1)\nos.close(2)\ntime.sleep(2.0)\n")
    started = time.monotonic()
    # Either timeout branch is correct -- whether the absolute deadline is
    # already spent at EOF, or expires during the bounded wait that follows.
    with pytest.raises(ProcessTimeout, match="torn down"):
        run_capture([sys.executable, str(script)], timeout=0.15, grace_seconds=1.0)
    elapsed = time.monotonic() - started
    assert elapsed < 0.15 + 1.0 + 0.5, (
        f"took {elapsed:.3f}s; the bound is the deadline plus one teardown budget"
    )


def test_the_teardown_budget_is_spent_once_not_once_per_phase(tmp_path, monkeypatch):
    """R4.2: TERM, KILL, reap and the group sweep share one total budget.

    Each phase used to start its own window, so a stubborn child could consume
    the grace several times over.
    """
    from animalite.proc import ManagedProcess

    script = tmp_path / "ignores_term.py"
    script.write_text(
        "import signal, time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\ntime.sleep(30)\n"
    )
    budget = 0.5
    proc = ManagedProcess([sys.executable, str(script)], grace_seconds=budget)
    try:
        time.sleep(0.15)
        # Force every phase to be exercised: the group never reports clear.
        monkeypatch.setattr(proc, "_group_alive", lambda: True)
        started = time.monotonic()
        proc.terminate_tree()
        elapsed = time.monotonic() - started
    finally:
        proc.process.kill()
    assert elapsed < budget * 1.6, (
        f"teardown took {elapsed:.3f}s against a {budget:.2f}s total budget; "
        "the budget is being spent per phase"
    )
    assert proc.survivors, "a group that never clears must be reported as a survivor"


def test_an_expired_deadline_stops_the_pipeline_instead_of_renewing_it(tmp_path, fixture_anchors):
    """R4.2: `max(0.1, ...)` handed every later stage a fresh 100 ms.

    An expired job deadline must prevent the next native child from launching,
    not grant it another allowance.
    """
    service = _service_with(SlowAdapter(), tmp_path, "expiring-profile")
    record = service.render_blocking(
        make_request(fixture_anchors, profile_id="expiring-profile", timeout_seconds=0.3)
    )
    assert record.state is JobState.FAILED
    assert record.failure is not None
    assert record.failure.category is FailureCategory.TIMEOUT
    _assert_no_published_output(record)


# --- R4.3 round 3: a leaked process is a failed attempt ----------------------


def test_a_surviving_encoder_group_fails_the_attempt_and_publishes_nothing(
    tmp_path, fixture_anchors
):
    """R4.3: survivors were merely noted, then the run went on to publish.

    A leaked encoder still holds CPU, memory and descriptors; reporting a clean
    run that was not clean is exactly what the cleanup guarantee forbids.
    """
    from unittest.mock import patch

    from animalite.media import encode as encode_module

    real_encode = encode_module.encode_delivery_stream

    def leaky(*args, **kwargs):
        outcome = real_encode(*args, **kwargs)
        return encode_module.EncodeOutcome(
            frames_written=outcome.frames_written, survivors=(987654,)
        )

    import animalite.core.service as service_module

    service = LocalExecutionService(tmp_path / "ws", tools=FFmpegTools.discover())
    # The service imported the function by name, so both bindings are patched.
    with (
        patch.object(encode_module, "encode_delivery_stream", leaky),
        patch.object(service_module, "encode_delivery_stream", leaky),
    ):
        record = service.render_blocking(make_request(fixture_anchors))

    assert record.state is JobState.FAILED, "a leaked process group must fail the attempt"
    assert record.failure is not None
    assert record.failure.category is FailureCategory.CLEANUP_FAILED
    assert 987654 in record.cleanup_survivor_groups
    _assert_no_published_output(record)


def test_survivor_evidence_survives_an_exception(tmp_path):
    """R4.3: an exception cannot return a CaptureResult, so it carries the evidence."""
    from animalite.errors import JobTimeoutError
    from animalite.proc import ProcessTimeout

    exc = ProcessTimeout("boom", pid=42, elapsed_seconds=1.5, stderr_tail="tail", survivors=(7, 8))
    assert exc.survivors == (7, 8)
    assert isinstance(exc, TimeoutError), "existing `except TimeoutError` callers must still match"
    # And a wrapper must forward it rather than replace the evidence with nothing.
    wrapped = JobTimeoutError("wrapped", survivors=exc.survivors)
    assert wrapped.survivors == (7, 8)


# --- R4 round 4: the teardown budget is per lifecycle, not per call ----------


def test_teardown_and_close_share_one_lifecycle_budget(tmp_path, monkeypatch):
    """R4.2: a timeout path calls terminate_tree(), then close() calls it again.

    Each call used to start a fresh absolute budget, so one process lifecycle
    spent it twice: measured 0.200 s for the first teardown and 0.401 s once
    `close()` had run as well.
    """
    from animalite.proc import ManagedProcess

    script = tmp_path / "ignores_term.py"
    script.write_text(
        "import signal, time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\ntime.sleep(30)\n"
    )
    budget = 0.3
    proc = ManagedProcess([sys.executable, str(script)], grace_seconds=budget)
    try:
        time.sleep(0.15)
        monkeypatch.setattr(proc, "_group_alive", lambda: True)
        started = time.monotonic()
        proc.terminate_tree()
        proc.close()  # what the context manager does on the way out
        elapsed = time.monotonic() - started
        survivors_after = list(proc.survivors)
    finally:
        proc.process.kill()

    assert elapsed < budget * 1.6, (
        f"teardown plus close took {elapsed:.3f}s against a {budget:.2f}s lifecycle "
        "budget; the budget is being restarted per call"
    )
    assert survivors_after, "a later cleanup call must not erase the survivor evidence"


def test_an_encoder_that_hangs_after_the_last_frame_still_times_out(tmp_path):
    """R4.2: the final wait had `max(0.1, ...)`, renewing 100 ms past the deadline."""
    from unittest.mock import patch

    from animalite.contracts.profile import ThreadBudget
    from animalite.errors import JobTimeoutError
    from animalite.media import encode as encode_module

    output = PREVIEW_OUTPUT
    frame = b"\x00" * (output.width * output.height * 3)

    def frames():
        for _ in range(output.delivery_frame_count):
            yield frame

    # Consumes all of stdin, then lives well past the deadline.
    script = tmp_path / "drain_then_hang.py"
    script.write_text("import sys, time\nsys.stdin.buffer.read()\ntime.sleep(10)\n")
    destination = tmp_path / "hung.mp4"
    argv = [sys.executable, str(script)]
    with patch.object(encode_module, "encoder_argv", lambda *a, **k: argv):
        started = time.monotonic()
        with pytest.raises(JobTimeoutError):
            encode_module.encode_delivery_stream(
                FFmpegTools.discover(),
                frames(),
                output,
                destination,
                thread_budget=ThreadBudget(total_threads=4),
                timeout_seconds=0.5,
            )
        elapsed = time.monotonic() - started
    assert elapsed < 6.0, f"the hung encoder was waited on for {elapsed:.3f}s"
    assert not destination.exists(), "nothing may be published when the encoder hangs"


# --- R4.2 round 5: the teardown budget is the hard bound ---------------------


def test_a_stalled_reap_cannot_exceed_the_teardown_budget(tmp_path, monkeypatch):
    """SIGKILL does not prove the child is already dead.

    A process in uninterruptible sleep stays alive until it leaves that state,
    so the post-SIGKILL `wait()` can burn its whole timeout. An earlier version
    granted a fixed 0.5 s here, reasoning that it was only collecting a corpse;
    measured, a stalled reap turned a 0.100 s budget into 0.601 s. Simulated
    deterministically: `wait()` consumes its timeout and raises.
    """
    from animalite.proc import ManagedProcess

    script = tmp_path / "ignores_term.py"
    script.write_text(
        "import signal, time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\ntime.sleep(30)\n"
    )
    budget = 0.2
    proc = ManagedProcess([sys.executable, str(script)], grace_seconds=budget)
    real_wait = proc.process.wait
    try:
        time.sleep(0.1)

        def stalled_wait(timeout=None):
            if timeout:
                time.sleep(timeout)
            raise subprocess.TimeoutExpired(proc.argv, timeout or 0.0)

        monkeypatch.setattr(proc.process, "wait", stalled_wait)
        monkeypatch.setattr(proc, "_group_alive", lambda: True)

        started = time.monotonic()
        proc.terminate_tree()
        after_teardown = time.monotonic() - started
        proc.close()  # must not open a second wait
        total = time.monotonic() - started
    finally:
        monkeypatch.undo()
        proc.process.kill()
        real_wait()

    assert after_teardown <= budget + 0.25, (
        f"teardown took {after_teardown:.3f}s against a {budget:.2f}s budget; the "
        "post-SIGKILL reap is waiting outside the bound"
    )
    assert total <= budget + 0.3, (
        f"teardown plus close took {total:.3f}s; close() opened another wait"
    )
    assert proc.survivors, "a group that never clears must be retained as survivor evidence"


def test_a_zombie_is_not_reported_as_a_leaked_process_group(tmp_path):
    """A zombie holds no resources; calling it a survivor fails clean attempts.

    `killpg(gid, 0)` succeeds for a zombie because it still owns its pid, so the
    positive answer is confirmed against /proc.
    """
    from animalite.proc import ManagedProcess

    script = tmp_path / "exits_now.py"
    script.write_text("raise SystemExit(0)\n")
    proc = ManagedProcess([sys.executable, str(script)], grace_seconds=1.0)
    try:
        # Wait for the child to become a zombie without reaping it.
        deadline = time.monotonic() + 10.0
        state = ""
        while time.monotonic() < deadline:
            try:
                stat = Path(f"/proc/{proc.pid}/stat").read_text()
            except OSError:  # pragma: no cover - reaped by someone else
                break
            state = stat.rpartition(")")[2].split()[0]
            if state == "Z":
                break
            time.sleep(0.01)
        assert state == "Z", f"child never became a zombie (state {state!r})"

        assert not proc._group_alive(), "a zombie-only group must not count as alive"
    finally:
        proc.close()
    assert not proc.survivors, "a zombie must not be recorded as a leaked group"


# --- B-R6: timing and evidence on the failure path ---------------------------


class SlowThenFailingAdapter(FixtureAdapter):
    """Spends real time in one frame and then raises, like a failed inference."""

    key = "slow-then-failing"

    def synthesize(self, context):
        for index, frame in enumerate(super().synthesize(context)):
            if index == 3:
                time.sleep(0.3)
                raise RuntimeError("simulated inference failure after 0.3s of work")
            yield frame


def test_time_spent_in_a_failing_generator_call_is_charged_to_synthesis(tmp_path, fixture_anchors):
    """The elapsed time was added *after* a successful next(), so a failing call
    cost nothing. Measured before the fix: a call that spent 0.3 s and then
    raised produced ``temporal_synthesis=0.000597s`` and charged the 0.3 s to
    encode instead.
    """
    service = _service_with(SlowThenFailingAdapter(), tmp_path, "slow-failing-profile")
    record = service.render_blocking(
        make_request(fixture_anchors, profile_id="slow-failing-profile")
    )
    assert record.state is JobState.FAILED

    stages = {s.stage.value: s.wall_seconds for s in record.stages}
    assert stages["temporal_synthesis"] >= 0.3, (
        f"the failed call's 0.3s was not charged to synthesis: {stages}"
    )


def test_a_learned_profile_never_inherits_the_no_inference_runtime_note():
    """B-R6. A failed learned attempt asserted "Package A runs no inference
    runtime" and ``inference_device_status=not_applicable`` -- about a run that
    had launched a model. Absent evidence is pending, not not-applicable.
    """
    from animalite.adapters.rife_ncnn import RIFE_PROFILE
    from animalite.contracts.enums import EvidenceStatus
    from animalite.core.service import _device_evidence_before_adapter

    learned = _device_evidence_before_adapter(RIFE_PROFILE)
    assert learned.inference_device_status is EvidenceStatus.PENDING
    assert not any("no inference runtime" in note for note in learned.notes)
    assert any("recorded no device observation" in note for note in learned.notes)

    fixture = _device_evidence_before_adapter(FIXTURE_PROFILE)
    assert fixture.inference_device_status is EvidenceStatus.NOT_APPLICABLE
    assert any("executes no inference runtime" in note for note in fixture.notes)

    unreached = _device_evidence_before_adapter(None)
    assert unreached.inference_device_status is EvidenceStatus.PENDING
    assert any("did not reach an adapter" in note for note in unreached.notes)
