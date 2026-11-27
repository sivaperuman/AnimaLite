"""Failed-run retention and ledger integrity.

Section 12.0: a timeout or invalid output fails the sample and *remains in the
ledger*. These tests prove a weak case cannot be deleted, edited or reordered
into a pass.
"""

from __future__ import annotations

import json

import pytest

from animalite.bench.ledger import RunLedger
from animalite.contracts.benchmark import BenchmarkPlan, PlannedRun, RunRecord
from animalite.contracts.enums import FailureCategory, RunKind, RunOutcome
from animalite.contracts.job import FailureRecord
from animalite.core.logging import utc_now
from animalite.errors import LedgerIntegrityError


def _plan(n=3):
    runs = [
        PlannedRun(
            run_id=f"clip-{i}:warm_final:1",
            clip_id=f"clip-{i}",
            kind=RunKind.WARM_FINAL,
            repetition=1,
            order_index=i,
        )
        for i in range(n)
    ]
    return BenchmarkPlan(
        plan_id="plan-test",
        created_at=utc_now(),
        dataset_id="ds",
        dataset_digest="sha256:" + "0" * 64,
        host_id="host",
        profile_id="fixture-synthetic",
        profile_digest="sha256:" + "1" * 64,
        target_revision="v0.12-proposed",
        order_seed=1,
        planned_runs=runs,
    )


def _record(run_id, clip_id, outcome=RunOutcome.SUCCEEDED, wall=1.0):
    kwargs = {}
    if outcome is RunOutcome.SUCCEEDED:
        kwargs = {"wall_seconds": wall, "output_hash": "sha256:" + "2" * 64}
    else:
        kwargs = {"failure": FailureRecord(category=FailureCategory.TIMEOUT, message="timed out")}
    return RunRecord(
        run_id=run_id,
        plan_id="plan-test",
        clip_id=clip_id,
        kind=RunKind.WARM_FINAL,
        repetition=1,
        outcome=outcome,
        host_id="host",
        profile_id="fixture-synthetic",
        **kwargs,
    )


def test_a_failed_run_carries_no_latency_observation():
    with pytest.raises(ValueError, match="must not carry wall_seconds"):
        RunRecord(
            run_id="r",
            plan_id="p",
            clip_id="c",
            kind=RunKind.WARM_FINAL,
            repetition=1,
            outcome=RunOutcome.TIMEOUT,
            wall_seconds=1.0,
            host_id="h",
            profile_id="p",
        )


def test_a_succeeded_run_must_carry_a_timing_and_an_output_hash():
    with pytest.raises(ValueError, match="must carry wall_seconds"):
        RunRecord(
            run_id="r",
            plan_id="p",
            clip_id="c",
            kind=RunKind.WARM_FINAL,
            repetition=1,
            outcome=RunOutcome.SUCCEEDED,
            host_id="h",
            profile_id="p",
        )


def test_failed_and_timed_out_runs_stay_in_the_ledger(tmp_path):
    ledger = RunLedger(tmp_path / "ledger")
    plan = _plan(3)
    ledger.write_plan(plan)
    ledger.append(_record("clip-0:warm_final:1", "clip-0"))
    ledger.append(_record("clip-1:warm_final:1", "clip-1", RunOutcome.TIMEOUT))
    ledger.append(_record("clip-2:warm_final:1", "clip-2", RunOutcome.INVALID_OUTPUT))

    records = ledger.records()
    assert [r.outcome for r in records] == [
        RunOutcome.SUCCEEDED,
        RunOutcome.TIMEOUT,
        RunOutcome.INVALID_OUTPUT,
    ]
    assert ledger.verify(plan).ok


def test_deleting_a_weak_case_is_detected_as_a_missing_observation(tmp_path):
    ledger = RunLedger(tmp_path / "ledger")
    plan = _plan(3)
    ledger.write_plan(plan)
    ledger.append(_record("clip-0:warm_final:1", "clip-0"))
    ledger.append(_record("clip-1:warm_final:1", "clip-1", RunOutcome.TIMEOUT))
    ledger.append(_record("clip-2:warm_final:1", "clip-2"))
    assert ledger.verify(plan).ok

    # Remove the timeout line, as someone chasing a green result would.
    lines = ledger.runs_path.read_text().splitlines()
    ledger.runs_path.write_text("\n".join([lines[0], lines[2]]) + "\n")

    verification = ledger.verify(plan)
    assert not verification.ok
    assert verification.missing_run_ids == ["clip-1:warm_final:1"]
    assert any("previous digest" in p for p in verification.problems)


def test_editing_a_recorded_run_breaks_the_hash_chain(tmp_path):
    ledger = RunLedger(tmp_path / "ledger")
    plan = _plan(2)
    ledger.write_plan(plan)
    ledger.append(_record("clip-0:warm_final:1", "clip-0", wall=95.0))
    ledger.append(_record("clip-1:warm_final:1", "clip-1", wall=1.0))

    lines = [json.loads(line) for line in ledger.runs_path.read_text().splitlines()]
    lines[0]["record"]["wall_seconds"] = 1.0  # make a slow run look fast
    rewritten = "\n".join(json.dumps(item, sort_keys=True) for item in lines)
    ledger.runs_path.write_text(rewritten + "\n")

    verification = ledger.verify(plan)
    assert not verification.ok
    assert any("edited after it was written" in p for p in verification.problems)


def test_reordering_records_is_detected(tmp_path):
    ledger = RunLedger(tmp_path / "ledger")
    plan = _plan(2)
    ledger.write_plan(plan)
    ledger.append(_record("clip-0:warm_final:1", "clip-0"))
    ledger.append(_record("clip-1:warm_final:1", "clip-1"))

    lines = ledger.runs_path.read_text().splitlines()
    ledger.runs_path.write_text("\n".join(reversed(lines)) + "\n")
    assert not ledger.verify(plan).ok


def test_a_never_executed_planned_run_is_reported_as_missing(tmp_path):
    ledger = RunLedger(tmp_path / "ledger")
    plan = _plan(3)
    ledger.write_plan(plan)
    ledger.append(_record("clip-0:warm_final:1", "clip-0"))

    missing = ledger.missing_runs(plan)
    assert [m.run_id for m in missing] == [
        "clip-1:warm_final:1",
        "clip-2:warm_final:1",
    ]
    assert not ledger.verify(plan).ok


def test_an_unplanned_record_is_reported(tmp_path):
    ledger = RunLedger(tmp_path / "ledger")
    plan = _plan(1)
    ledger.write_plan(plan)
    ledger.append(_record("clip-0:warm_final:1", "clip-0"))
    ledger.append(_record("smuggled:warm_final:1", "smuggled"))
    verification = ledger.verify(plan)
    assert verification.unplanned_run_ids == ["smuggled:warm_final:1"]
    assert not verification.ok


def test_a_second_plan_cannot_overwrite_an_existing_ledger(tmp_path):
    ledger = RunLedger(tmp_path / "ledger")
    ledger.write_plan(_plan(1))
    with pytest.raises(LedgerIntegrityError, match="new ledger directory"):
        ledger.write_plan(_plan(2))
