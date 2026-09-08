"""Failure cleanup, timeouts, cancellation and retry semantics.

Handoff rules 4 and 5: a timeout, cancellation or crash must clean up the
process tree, retain diagnostics and never publish a partial encode as
successful output; a retry creates a new attempt linked to its parent.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest

from animalite.adapters.fixture import FIXTURE_PROFILE, FixtureAdapter
from animalite.adapters.registry import Registry
from animalite.contracts.enums import FailureCategory, JobState
from animalite.core.attempts import AttemptStore
from animalite.core.process import ManagedProcess, process_alive
from animalite.core.service import OUTPUT_FILENAME, LocalExecutionService
from animalite.errors import AttemptConflictError
from animalite.media.ffmpeg import FFmpegTools
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
