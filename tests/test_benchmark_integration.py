"""The benchmark harness drives the same execution path as the CLI."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from animalite.adapters.registry import default_registry
from animalite.bench.evaluate import build_report
from animalite.bench.ledger import RunLedger
from animalite.bench.runner import BenchmarkRunner, build_plan
from animalite.contracts.base import content_digest
from animalite.contracts.benchmark import (
    DatasetClip,
    DatasetManifest,
    HostRecord,
    TargetSet,
)
from animalite.contracts.enums import (
    FailureCategory,
    QualificationVerdict,
    RunKind,
    RunOutcome,
)
from animalite.fixtures.generator import FIXTURE_CLIPS, generate_clip, write_anchor_set

pytestmark = [pytest.mark.media, pytest.mark.slow]


@pytest.fixture()
def fixture_dataset(tmp_path, tools) -> DatasetManifest:
    clips = []
    for clip_id in ("fixture-two-anchor", "fixture-three-anchor"):
        clip = FIXTURE_CLIPS[clip_id]
        anchors = generate_clip(clip, tmp_path / clip_id, tools=tools)
        manifest = write_anchor_set(anchors, tmp_path / clip_id / "anchors.json")
        clips.append(
            DatasetClip(
                clip_id=clip_id,
                category="fixture",
                anchor_count=anchors.count,
                anchor_manifest_path=str(manifest),
                anchor_hashes=[a.asset.content_hash for a in anchors.anchors],
            )
        )
    return DatasetManifest(dataset_id="fixture-development", clips=clips)


def _run(tmp_path, dataset, *, warm=1, cold=1, preview=1, profile_override=None):
    registry = default_registry()
    if profile_override is not None:
        registry.register_profile(profile_override)
    profile = registry.profile("fixture-synthetic")
    host = HostRecord(host_id="development-unapproved")
    plan = build_plan(
        dataset=dataset,
        host=host,
        profile_id=profile.profile_id,
        profile_digest=content_digest(profile),
        target_revision="v0.12-proposed",
        order_seed=42,
        warm_repetitions=warm,
        cold_repetitions=cold,
        preview_repetitions=preview,
    )
    ledger = RunLedger(tmp_path / "ledger")
    ledger.write_plan(plan)
    runner = BenchmarkRunner(
        dataset=dataset,
        host=host,
        profile_id=profile.profile_id,
        workspace=tmp_path / "bench",
        ledger=ledger,
        registry=registry,
    )
    runner.run(plan)
    report = build_report(
        plan=plan,
        dataset=dataset,
        host=host,
        profile=profile,
        targets=TargetSet(),
        ledger=ledger,
    )
    return plan, ledger, report


def test_the_harness_records_every_planned_run_and_refuses_qualification(tmp_path, fixture_dataset):
    plan, ledger, report = _run(tmp_path, fixture_dataset)

    assert len(plan.planned_runs) == 2 * 3  # 2 clips x (warm + cold + preview)
    records = ledger.records()
    assert {r.run_id for r in records} == plan.run_ids()
    assert all(r.outcome is RunOutcome.SUCCEEDED for r in records), [
        (r.run_id, r.outcome, r.failure) for r in records if r.outcome is not RunOutcome.SUCCEEDED
    ]
    assert ledger.verify(plan).ok

    assert report.verdict is QualificationVerdict.NOT_ELIGIBLE
    assert report.exploratory
    assert "NOT QUALIFICATION EVIDENCE" in report.label
    codes = {f.code for f in report.blocking_findings}
    assert "ELIG-PROFILE-NOT-LEARNED" in codes
    assert "ELIG-HOST-UNAPPROVED" in codes
    assert "ELIG-TARGETS-UNAPPROVED" in codes


def test_every_run_record_is_marked_exploratory_and_non_eligible(tmp_path, fixture_dataset):
    _, ledger, _ = _run(tmp_path, fixture_dataset)
    for record in ledger.records():
        assert record.exploratory is True
        assert record.qualification_eligible_profile is False
        assert record.environment is not None
        assert record.environment.animalite_version
        assert record.output_hash is not None


def test_warm_and_cold_runs_are_recorded_with_distinct_boundaries(tmp_path, fixture_dataset):
    _, ledger, report = _run(tmp_path, fixture_dataset)
    kinds = {r.kind for r in ledger.records()}
    assert kinds == {RunKind.WARM_FINAL, RunKind.COLD_FINAL, RunKind.WARM_PREVIEW}
    summaries = {s.kind: s for s in report.distributions}
    # Cold runs rebuild the service inside the boundary, so they are never faster
    # than the warm p95 by construction of the measurement, and each kind is
    # reported separately rather than pooled.
    for kind in kinds:
        assert summaries[kind].n_succeeded == summaries[kind].n_planned
        assert summaries[kind].p95_seconds is not None


def test_preview_runs_use_the_preview_output_spec(tmp_path, fixture_dataset):
    _, ledger, _ = _run(tmp_path, fixture_dataset)
    preview = [r for r in ledger.records() if r.kind is RunKind.WARM_PREVIEW]
    assert preview
    for record in preview:
        assert record.frame_accounting is not None
        assert record.frame_accounting.animation_frame_count == 36
        assert record.frame_accounting.delivery_frame_count == 72


def test_the_written_report_is_json_and_carries_the_exploratory_label(tmp_path, fixture_dataset):
    _, _, report = _run(tmp_path, fixture_dataset)
    path = Path(tmp_path / "report.json")
    path.write_text(json.dumps(report.to_json_obj(), indent=2, sort_keys=True))
    payload = json.loads(path.read_text())
    assert payload["verdict"] == "not_eligible"
    assert payload["exploratory"] is True
    assert payload["profile_qualification_eligible"] is False
    assert payload["host_approved"] is False
    assert payload["ledger_verified"] is True


def test_a_missing_anchor_manifest_is_recorded_as_not_run(tmp_path, fixture_dataset):
    broken = fixture_dataset.model_copy(
        update={
            "clips": [
                *fixture_dataset.clips,
                DatasetClip(
                    clip_id="missing-clip",
                    category="fixture",
                    anchor_count=2,
                    anchor_manifest_path=str(tmp_path / "does-not-exist.json"),
                ),
            ]
        }
    )
    _, broken_ledger, report = _run(tmp_path, broken)
    missing = [r for r in broken_ledger.records() if r.clip_id == "missing-clip"]
    assert missing and all(r.outcome is RunOutcome.NOT_RUN for r in missing)
    assert all(r.wall_seconds is None for r in missing)
    assert "OBS-FAILED-RUNS" in {f.code for f in report.blocking_findings}


# --- R3 regression: process-cold must be a genuinely fresh process ------------


def test_cold_runs_execute_in_a_different_process_from_the_warm_service(tmp_path, fixture_dataset):
    """Rebuilding the service in-process is not process-cold.

    Previously the cold branch constructed a new `LocalExecutionService` in the
    same interpreter and reused the same `Registry` and adapter instance, so
    imports, native initialisation and any resident model state were already
    warm. The cold run now launches a child interpreter, and its identity is
    recorded as evidence.
    """
    import os

    _, ledger, _ = _run(tmp_path, fixture_dataset, warm=1, cold=1, preview=0)
    records = ledger.records()
    cold = [r for r in records if r.kind is RunKind.COLD_FINAL]
    assert cold, "no cold runs were executed"

    for record in cold:
        assert record.outcome is RunOutcome.SUCCEEDED, record.failure
        evidence = record.cold_process_evidence
        assert evidence is not None, "cold runs must carry process evidence"
        assert evidence.parent_pid == os.getpid()
        assert evidence.interpreter
        assert "-m" in evidence.argv and "animalite" in evidence.argv
        # Section 12.0 permits a warm OS cache but requires it disclosed.
        assert evidence.os_file_cache_cleared is False
        assert any("not disk-cold" in note for note in evidence.notes)


def test_the_cold_clock_starts_before_the_child_is_launched(tmp_path, fixture_dataset, monkeypatch):
    """Timer placement, proved by controlled startup work rather than by racing.

    Comparing `min(cold) > min(warm)` on a shared CI runner is not a correctness
    invariant: it can fail from noise alone. Instead a known delay is injected
    at the launch boundary and the recorded cold wall time is required to have
    absorbed it -- which is only true if the clock started before the launch.
    """
    import animalite.bench.runner as runner_module

    injected = 0.75
    real_capture = runner_module.run_capture

    def slow_launch(*args, **kwargs):
        time.sleep(injected)
        return real_capture(*args, **kwargs)

    baseline_run = _run(tmp_path / "baseline", fixture_dataset, warm=0, cold=1, preview=0)
    baseline = [
        r.wall_seconds
        for r in baseline_run[1].records()
        if r.kind is RunKind.COLD_FINAL and r.wall_seconds
    ]
    assert baseline, "no cold run to use as a baseline"

    monkeypatch.setattr(runner_module, "run_capture", slow_launch)
    _, ledger, _ = _run(tmp_path / "delayed", fixture_dataset, warm=0, cold=1, preview=0)
    delayed = [
        r.wall_seconds for r in ledger.records() if r.kind is RunKind.COLD_FINAL and r.wall_seconds
    ]
    assert delayed, "no cold run was recorded with the injected delay"
    assert min(delayed) >= min(baseline) + injected * 0.8, (
        f"cold wall {min(delayed):.3f}s did not absorb the {injected:.2f}s injected at the "
        f"launch boundary (baseline {min(baseline):.3f}s); the clock is starting too late"
    )


def test_a_cold_run_executes_the_profile_the_parent_resolved(tmp_path, fixture_dataset):
    """R3: the child must not substitute a same-named profile of its own.

    The child used to receive only `engine_profile_id` and rebuild the default
    registry. With an overridden `fixture-synthetic` registered in the parent,
    the warm run produced one output and the cold run produced the *default*
    profile's output, while both recorded success under the same planned
    profile. Identical settings must now yield identical bytes on both paths.
    """
    overridden = (
        default_registry()
        .profile("fixture-synthetic")
        .model_copy(update={"parameters": {"ease": "linear", "drift_pixels": 12.0}})
    )
    _, ledger, _ = _run(
        tmp_path, fixture_dataset, warm=1, cold=1, preview=0, profile_override=overridden
    )
    records = ledger.records()
    by_clip: dict[str, dict[RunKind, str]] = {}
    for record in records:
        if record.outcome is RunOutcome.SUCCEEDED and record.output_hash:
            by_clip.setdefault(record.clip_id, {})[record.kind] = record.output_hash

    compared = 0
    for clip_id, hashes in by_clip.items():
        warm_hash = hashes.get(RunKind.WARM_FINAL)
        cold_hash = hashes.get(RunKind.COLD_FINAL)
        if warm_hash and cold_hash:
            compared += 1
            assert warm_hash == cold_hash, (
                f"{clip_id}: cold output {cold_hash} differs from warm {warm_hash} under "
                "identical settings; the child executed a different resolved profile"
            )
    assert compared, "no clip produced both a warm and a cold output to compare"


def test_two_cold_runs_report_distinct_real_process_instances(tmp_path, fixture_dataset):
    """R3: prove freshness from the child's own identity, not the parent's pid.

    The old evidence read `completed.pid`, which `subprocess.CompletedProcess`
    does not have, so `child_pid` was always null and the "different process"
    check only ever asserted things about the parent.
    """
    import os

    _, ledger, _ = _run(tmp_path, fixture_dataset, warm=0, cold=2, preview=0)
    cold = [r for r in ledger.records() if r.kind is RunKind.COLD_FINAL]
    assert len(cold) >= 2, "need at least two cold runs to compare instances"

    keys = set()
    for record in cold:
        assert record.outcome is RunOutcome.SUCCEEDED, record.failure
        evidence = record.cold_process_evidence
        assert evidence is not None
        assert evidence.child_pid is not None and evidence.child_pid > 0
        assert evidence.child_pid != os.getpid()
        assert evidence.child_instance is not None, "the child must report its own instance"
        assert evidence.child_instance.pid == evidence.child_pid
        assert evidence.is_distinct_process, "child and parent are not provably distinct"
        assert not evidence.child_survivor_groups, (
            f"cold run {record.run_id} left process group(s) {evidence.child_survivor_groups} alive"
        )
        keys.add(evidence.child_instance.instance_key)

    assert len(keys) == len(cold), (
        f"two cold runs shared a process instance key: {keys}; they were not fresh processes"
    )


def test_a_setup_failure_records_the_run_and_continues_the_plan(tmp_path, fixture_dataset):
    """A run that never reaches a service attempt is still recorded."""
    broken = fixture_dataset.model_copy(
        update={
            "clips": [
                *fixture_dataset.clips,
                DatasetClip(
                    clip_id="unreadable",
                    category="fixture",
                    anchor_count=2,
                    anchor_manifest_path=str(tmp_path / "nope.json"),
                ),
            ]
        }
    )
    plan, ledger, _ = _run(tmp_path, broken, warm=1, cold=0, preview=0)
    recorded = {r.run_id for r in ledger.records()}
    # Every planned run has a record, including the one that could not start.
    assert recorded == plan.run_ids()
    failed = [r for r in ledger.records() if r.clip_id == "unreadable"]
    assert failed and all(r.wall_seconds is None for r in failed)


# --- R3/R4 regression: a failing child is retained, a broken launch is contained


def _cold_only(tmp_path, dataset, **kwargs):
    """Build a runner and a one-clip cold-only plan without executing it."""
    registry = default_registry()
    profile = registry.profile("fixture-synthetic")
    host = HostRecord(host_id="development-unapproved")
    plan = build_plan(
        dataset=dataset,
        host=host,
        profile_id=profile.profile_id,
        profile_digest=content_digest(profile),
        target_revision="v0.12-proposed",
        order_seed=42,
        warm_repetitions=0,
        cold_repetitions=kwargs.pop("cold", 1),
        preview_repetitions=0,
    )
    ledger = RunLedger(tmp_path / "ledger")
    ledger.write_plan(plan)
    runner = BenchmarkRunner(
        dataset=dataset,
        host=host,
        profile_id=profile.profile_id,
        workspace=tmp_path / "bench",
        ledger=ledger,
        registry=registry,
        **kwargs,
    )
    return plan, ledger, runner


def test_a_child_that_times_out_keeps_its_attempt_id_and_category(tmp_path, fixture_dataset):
    """R3/R4: a clean child failure must not become an anonymous internal error.

    The child writes a complete failed AttemptRecord and exits 1. Rejecting a
    nonzero exit *before* parsing stdout discarded the attempt id, the timeout
    category and the diagnostics directory the child had already retained.
    """
    plan, _ledger, runner = _cold_only(tmp_path, fixture_dataset, timeout_seconds=0.35)
    planned = sorted(plan.planned_runs, key=lambda r: r.order_index)[0]
    record = runner.run_one(plan, planned)

    assert record.outcome is RunOutcome.TIMEOUT
    assert record.attempt_id, "the child's attempt id was lost"
    assert record.failure is not None
    assert record.failure.category is FailureCategory.TIMEOUT
    assert record.failure.diagnostics_path, "the child's diagnostics were not linked"
    assert Path(record.failure.diagnostics_path).exists()
    # Failure latency is retained, but never as a latency observation.
    assert record.wall_seconds is None
    assert record.failure_elapsed_seconds is not None and record.failure_elapsed_seconds > 0


def test_a_launcher_exception_is_recorded_and_the_plan_continues(
    tmp_path, fixture_dataset, monkeypatch
):
    """R3/R4: an exception at the launch boundary must not abandon the plan.

    Injecting `subprocess.TimeoutExpired` at the cold launch previously escaped
    `run_one()` and aborted `run()` before the ledger append, losing the current
    record and every remaining planned run.
    """
    import subprocess

    import animalite.bench.runner as runner_module

    def boom(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=["python"], timeout=1.0)

    plan, ledger, runner = _cold_only(tmp_path, fixture_dataset, cold=2)
    monkeypatch.setattr(runner_module, "run_capture", boom)
    records = runner.run(plan)

    assert len(records) == len(plan.planned_runs)
    assert {r.run_id for r in ledger.records()} == plan.run_ids()
    assert all(r.outcome is not RunOutcome.SUCCEEDED for r in records)
    assert all(r.wall_seconds is None for r in records)


def test_a_child_that_writes_no_record_is_recorded_as_failed(
    tmp_path, fixture_dataset, monkeypatch
):
    """R3/R4: malformed or absent child output is an explicit record, not a crash."""
    import animalite.bench.runner as runner_module
    from animalite.proc import CaptureResult

    def garbage(*_args, **_kwargs):
        return CaptureResult(
            returncode=1,
            stdout=b"not json at all",
            stderr=b"child exploded",
            pid=424242,
            elapsed_seconds=0.01,
        )

    plan, _ledger, runner = _cold_only(tmp_path, fixture_dataset)
    monkeypatch.setattr(runner_module, "run_capture", garbage)
    planned = sorted(plan.planned_runs, key=lambda r: r.order_index)[0]
    record = runner.run_one(plan, planned)

    assert record.outcome is RunOutcome.FAILED
    assert record.wall_seconds is None
    assert record.failure is not None and "child exploded" in record.failure.message
    assert record.cold_process_evidence is not None
    assert record.cold_process_evidence.child_pid == 424242


def test_success_json_with_a_failing_exit_status_is_refused(tmp_path, fixture_dataset):
    """R3/R4: a record contradicting the process status is a protocol error.

    Accepting the JSON would let a child that actually failed report a pass.
    """
    import animalite.bench.runner as runner_module
    from animalite.proc import CaptureResult

    plan, _ledger, runner = _cold_only(tmp_path, fixture_dataset)
    planned = sorted(plan.planned_runs, key=lambda r: r.order_index)[0]
    honest = runner.run_one(plan, planned)
    assert honest.outcome is RunOutcome.SUCCEEDED, honest.failure

    attempt_json = (
        Path(runner.workspace / "cold" / planned.run_id / "ws")
        .rglob("attempt.json")
        .__next__()
        .read_bytes()
    )

    def lying_child(*_args, **_kwargs):
        return CaptureResult(
            returncode=1,
            stdout=attempt_json,
            stderr=b"",
            pid=999,
            elapsed_seconds=0.01,
        )

    runner_module.run_capture, real = lying_child, runner_module.run_capture
    try:
        record = runner.run_one(plan, planned)
    finally:
        runner_module.run_capture = real

    assert record.outcome is RunOutcome.FAILED
    assert record.wall_seconds is None
    assert record.failure is not None
    assert "contradicts" in record.failure.message


def test_a_supervisor_timeout_is_recorded_and_the_next_run_still_executes(
    tmp_path, fixture_dataset, monkeypatch
):
    """R3/R4: one launch-to-completion deadline, then the plan carries on."""
    import animalite.bench.runner as runner_module

    plan, ledger, runner = _cold_only(tmp_path, fixture_dataset, cold=2)
    calls = {"n": 0}
    real_capture = runner_module.run_capture

    def first_call_hangs(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("supervised child exceeded its deadline")
        return real_capture(*args, **kwargs)

    monkeypatch.setattr(runner_module, "run_capture", first_call_hangs)
    records = runner.run(plan)

    assert {r.run_id for r in ledger.records()} == plan.run_ids()
    timed_out = [r for r in records if r.outcome is RunOutcome.TIMEOUT]
    succeeded = [r for r in records if r.outcome is RunOutcome.SUCCEEDED]
    assert timed_out, "the supervisor timeout was not recorded as a timeout"
    assert timed_out[0].failure is not None
    assert timed_out[0].failure.category is FailureCategory.TIMEOUT
    assert timed_out[0].wall_seconds is None
    assert succeeded, "the plan did not continue after the supervisor timeout"


# --- R3 round 3: the media tools must be bound across the boundary too -------


def test_an_explicitly_selected_tool_pair_round_trips_to_the_cold_child(
    tmp_path, fixture_dataset, tools
):
    """The child must execute the parent's selection, not rediscover its own.

    With the parent holding injected identities, warm ran under those and cold
    silently ran under the host-discovered FFmpeg, both reporting success under
    one plan. Equal output was incidental: the paths happened to be the same
    binaries.
    """
    _, ledger, _ = _run(tmp_path, fixture_dataset, warm=1, cold=1, preview=0)
    cold = [r for r in ledger.records() if r.kind is RunKind.COLD_FINAL]
    warm = [r for r in ledger.records() if r.kind is RunKind.WARM_FINAL]
    assert cold and warm

    selected = tools.with_content_hashes().selection()
    for record in cold + warm:
        assert record.outcome is RunOutcome.SUCCEEDED, record.failure
        assert record.environment is not None
        executed = record.environment.media_tools
        assert executed is not None, "every run must record the tools it executed with"
        assert executed.ffmpeg.content_hash and executed.ffprobe.content_hash, (
            f"{record.run_id} recorded no executable content hash, so its tools are unverified"
        )
        assert not selected.mismatches(executed), (
            f"{record.run_id} ran different tools than were selected"
        )


def test_a_cold_child_running_different_tools_is_not_a_successful_run(
    tmp_path, fixture_dataset, tools
):
    """R3: a tool substitution must fail closed, not pass with equal output."""
    from animalite.media.ffmpeg import FFmpegTools

    injected = FFmpegTools(
        ffmpeg=tools.ffmpeg.model_copy(update={"version": "PARENT-ONLY-NOT-ON-THIS-HOST"}),
        ffprobe=tools.ffprobe.model_copy(update={"version": "PARENT-ONLY-NOT-ON-THIS-HOST"}),
    )
    registry = default_registry()
    profile = registry.profile("fixture-synthetic")
    host = HostRecord(host_id="development-unapproved")
    plan = build_plan(
        dataset=fixture_dataset,
        host=host,
        profile_id=profile.profile_id,
        profile_digest=content_digest(profile),
        target_revision="v0.12-proposed",
        order_seed=42,
        warm_repetitions=0,
        cold_repetitions=1,
        preview_repetitions=0,
    )
    ledger = RunLedger(tmp_path / "ledger")
    ledger.write_plan(plan)
    runner = BenchmarkRunner(
        dataset=fixture_dataset,
        host=host,
        profile_id=profile.profile_id,
        workspace=tmp_path / "bench",
        ledger=ledger,
        registry=registry,
        tools=injected,
    )
    planned = sorted(plan.planned_runs, key=lambda r: r.order_index)[0]
    record = runner.run_one(plan, planned)

    assert record.outcome is not RunOutcome.SUCCEEDED
    assert record.wall_seconds is None, "a substituted-tool run must contribute no observation"


@pytest.mark.parametrize(
    ("corruption", "expected"),
    [
        ("delete", "no start marker"),
        ("wrong_pid", "does not describe the process"),
        ("unidentified", "pid alone"),
    ],
)
def test_incomplete_cold_process_evidence_is_not_a_successful_run(
    tmp_path, fixture_dataset, monkeypatch, corruption, expected
):
    """R3: fail closed. An unverifiable cold sample is not weaker evidence, it is none."""
    import animalite.bench.runner as runner_module
    from animalite.contracts.job import ProcessInstance

    plan, _ledger, runner = _cold_only(tmp_path, fixture_dataset)
    planned = sorted(plan.planned_runs, key=lambda r: r.order_index)[0]
    real_capture = runner_module.run_capture

    def tamper(*args, **kwargs):
        result = real_capture(*args, **kwargs)
        marker = tmp_path / "bench" / "cold" / planned.run_id / "process.json"
        if corruption == "delete":
            marker.unlink(missing_ok=True)
        else:
            instance = ProcessInstance.model_validate_json(marker.read_text(encoding="utf-8"))
            if corruption == "wrong_pid":
                instance = instance.model_copy(update={"pid": instance.pid + 100000})
            else:
                instance = instance.model_copy(update={"boot_id": None, "start_ticks": None})
            marker.write_text(instance.model_dump_json(indent=2), encoding="utf-8")
        return result

    monkeypatch.setattr(runner_module, "run_capture", tamper)
    record = runner.run_one(plan, planned)

    assert record.outcome is not RunOutcome.SUCCEEDED
    assert record.wall_seconds is None
    assert record.failure is not None and expected in record.failure.message


def test_a_cold_run_that_leaks_a_process_group_is_not_successful(
    tmp_path, fixture_dataset, monkeypatch
):
    """R4.3: a leaked process is a cleanup failure, and it reaches the ledger."""
    import animalite.bench.runner as runner_module
    from animalite.proc import CaptureResult

    plan, ledger, runner = _cold_only(tmp_path, fixture_dataset)
    planned = sorted(plan.planned_runs, key=lambda r: r.order_index)[0]
    real_capture = runner_module.run_capture

    def leaky(*args, **kwargs):
        result = real_capture(*args, **kwargs)
        return CaptureResult(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            pid=result.pid,
            elapsed_seconds=result.elapsed_seconds,
            survivors=(555001,),
        )

    monkeypatch.setattr(runner_module, "run_capture", leaky)
    record = runner.run_one(plan, planned)
    ledger.append(record)

    assert record.outcome is not RunOutcome.SUCCEEDED
    assert record.wall_seconds is None
    assert 555001 in record.cleanup_survivor_groups, "survivors must reach the ledger"
    assert [r for r in ledger.records() if 555001 in r.cleanup_survivor_groups]


# --- R3/R4 round 4: the tool contract is mandatory, evidence survives timeout -


def test_a_parent_without_usable_tools_launches_no_cold_child(tmp_path, fixture_dataset):
    """R3: the contract used to switch itself off when the parent had no pair.

    Measured before: with an unavailable pair injected into the parent and host
    FFmpeg still on PATH, the cold run reported `succeeded` having executed
    `/usr/bin/ffmpeg` — the same class of configuration substitution R3 exists
    to prevent.
    """
    from animalite.contracts.host import ToolIdentity
    from animalite.media.ffmpeg import FFmpegTools

    unusable = FFmpegTools(
        ffmpeg=ToolIdentity(name="ffmpeg", available=False, error="injected"),
        ffprobe=ToolIdentity(name="ffprobe", available=False, error="injected"),
    )
    plan, _ledger, runner = _cold_only(tmp_path, fixture_dataset, tools=unusable)
    planned = sorted(plan.planned_runs, key=lambda r: r.order_index)[0]
    record = runner.run_one(plan, planned)

    assert record.outcome is not RunOutcome.SUCCEEDED
    assert record.failure is not None
    assert record.failure.category is FailureCategory.TOOL_UNAVAILABLE
    assert record.wall_seconds is None
    assert record.environment is None or record.environment.media_tools is None, (
        "no child should have been launched, so nothing should have executed"
    )


def test_two_absent_content_hashes_are_not_a_match():
    """R3: unverified is not equal. Two missing hashes are two unknown binaries."""
    from animalite.contracts.host import ToolIdentity
    from animalite.contracts.job import MediaToolSelection

    bare = MediaToolSelection(
        ffmpeg=ToolIdentity(name="ffmpeg", available=True, path="/usr/bin/ffmpeg"),
        ffprobe=ToolIdentity(name="ffprobe", available=True, path="/usr/bin/ffprobe"),
    )
    problems = bare.mismatches(bare)
    assert problems, "both hashes absent must not compare equal"
    assert all("unverified" in p for p in problems)


def test_a_structured_outer_timeout_keeps_its_pid_and_survivors(
    tmp_path, fixture_dataset, monkeypatch
):
    """R4.3: the cold timeout path caught the exception but dropped its fields.

    Measured before: an injected `ProcessTimeout(pid=424242, survivors=(777,))`
    produced `cold_process_evidence=None` and `cleanup_survivor_groups=[]`.
    """
    import animalite.bench.runner as runner_module
    from animalite.proc import ProcessTimeout

    def structured_timeout(*_args, **_kwargs):
        raise ProcessTimeout("injected", pid=424242, elapsed_seconds=1.0, survivors=(777,))

    plan, _ledger, runner = _cold_only(tmp_path, fixture_dataset)
    planned = sorted(plan.planned_runs, key=lambda r: r.order_index)[0]
    monkeypatch.setattr(runner_module, "run_capture", structured_timeout)
    record = runner.run_one(plan, planned)

    assert record.outcome is RunOutcome.TIMEOUT
    assert record.cold_process_evidence is not None
    assert record.cold_process_evidence.child_pid == 424242
    assert record.cold_process_evidence.child_survivor_groups == [777]
    assert record.cleanup_survivor_groups == [777]


def test_a_plain_timeout_records_what_it_knows_without_inventing_the_rest(
    tmp_path, fixture_dataset, monkeypatch
):
    """A third-party TimeoutError legitimately knows no pid; it must not fake one."""
    import animalite.bench.runner as runner_module

    def plain_timeout(*_args, **_kwargs):
        raise TimeoutError("something else timed out")

    plan, _ledger, runner = _cold_only(tmp_path, fixture_dataset)
    planned = sorted(plan.planned_runs, key=lambda r: r.order_index)[0]
    monkeypatch.setattr(runner_module, "run_capture", plain_timeout)
    record = runner.run_one(plan, planned)

    assert record.outcome is RunOutcome.TIMEOUT
    assert record.cold_process_evidence is not None
    assert record.cold_process_evidence.child_pid is None
    assert record.cleanup_survivor_groups == []
