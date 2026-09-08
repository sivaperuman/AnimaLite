"""The benchmark harness drives the same execution path as the CLI."""

from __future__ import annotations

import json
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
from animalite.contracts.enums import QualificationVerdict, RunKind, RunOutcome
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


def _run(tmp_path, dataset, *, warm=1, cold=1, preview=1):
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


def test_cold_runs_are_not_faster_than_warm_runs(tmp_path, fixture_dataset):
    """Interpreter startup is inside the cold boundary, so cold >= warm.

    A cold run measuring faster than a warm one would mean initialisation had
    escaped the boundary.
    """
    _, ledger, _ = _run(tmp_path, fixture_dataset, warm=1, cold=1, preview=0)
    records = ledger.records()
    warm = [r.wall_seconds for r in records if r.kind is RunKind.WARM_FINAL and r.wall_seconds]
    cold = [r.wall_seconds for r in records if r.kind is RunKind.COLD_FINAL and r.wall_seconds]
    assert warm and cold
    assert min(cold) > min(warm), (
        f"cold {min(cold):.3f}s is not slower than warm {min(warm):.3f}s; "
        "initialisation may be escaping the cold boundary"
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
