"""The evaluator must refuse a qualification pass without complete evidence.

Handoff section 13: "A fixture adapter, unapproved host or missing
quality/device/memory evidence cannot receive a model-qualification pass."

The strategy here is to build a *fully complete, fully passing* synthetic
evidence set, confirm it qualifies, and then remove exactly one thing at a time
to prove each condition is genuinely load-bearing.
"""

from __future__ import annotations

import pytest

from animalite.bench.evaluate import build_report, distributions_for, evaluate_eligibility
from animalite.bench.ledger import RunLedger
from animalite.contracts.benchmark import (
    BenchmarkPlan,
    ContinuousWorkloadRecord,
    DatasetClip,
    DatasetManifest,
    EvidenceBundle,
    FreshInputPackRecord,
    HostRecord,
    PlannedRun,
    QualityReview,
    RunRecord,
    TargetSet,
    UnsupportedCaseRecord,
)
from animalite.contracts.enums import (
    EndpointControlMode,
    EngineClass,
    EvidenceStatus,
    FailureCategory,
    MemoryMethod,
    MotionTier,
    QualificationVerdict,
    RunKind,
    RunOutcome,
)
from animalite.contracts.host import HostApproval
from animalite.contracts.job import FailureRecord
from animalite.contracts.profile import EngineProfile, Resolution, ThreadBudget
from animalite.contracts.results import MemoryObservation
from animalite.core.logging import utc_now
from animalite.hostinfo.inventory import collect_inventory

CATEGORIES = ["face_reaction"] * 4 + ["gesture_body"] * 4 + ["cloth_hair_overlap"] * 4


def learned_profile() -> EngineProfile:
    """A hypothetical Package B profile. Nothing like it is implemented yet."""
    return EngineProfile(
        profile_id="hypothetical-learned",
        display_name="hypothetical learned CPU profile (test double)",
        adapter_key="fixture-synthetic",
        engine_class=EngineClass.ML_ASSISTED,
        learned_temporal_participation=True,
        qualification_eligible=True,
        supported_tiers=[MotionTier.E3],
        supported_tasks=["temporal_interpolation"],
        supported_endpoint_modes=[EndpointControlMode.DETERMINISTIC_STATE],
        supported_resolutions=[Resolution(width=640, height=360)],
        thread_budget=ThreadBudget(total_threads=4),
    )


def locked_dataset() -> DatasetManifest:
    clips = []
    for index, category in enumerate(CATEGORIES):
        clips.append(
            DatasetClip(
                clip_id=f"clip-{index:02d}",
                category=category,
                anchor_count=2 if index < 2 else 4,
                anchor_manifest_path=f"/nonexistent/clip-{index:02d}.json",
            )
        )
    return DatasetManifest(
        dataset_id="p-l-qualification-sample",
        revision=1,
        purpose="qualification",
        locked=True,
        clips=clips,
    )


def approved_host() -> HostRecord:
    return HostRecord(
        host_id="p-l-approved",
        approval=HostApproval(
            approved=True, decision_id="D-02", approved_by="project owner + technical lead"
        ),
        inventory=collect_inventory(),
        power_policy="sustained, balanced governor pinned",
        thermal_policy="no throttling permitted; recorded per run",
    )


def approved_targets() -> TargetSet:
    return TargetSet(approved=True, approval_decision_id="D-02")


def full_plan(dataset: DatasetManifest) -> BenchmarkPlan:
    runs = []
    order = 0
    for clip in dataset.clips:
        for kind, count in (
            (RunKind.WARM_FINAL, 3),
            (RunKind.COLD_FINAL, 1),
            (RunKind.WARM_PREVIEW, 3),
        ):
            for repetition in range(1, count + 1):
                runs.append(
                    PlannedRun(
                        run_id=f"{clip.clip_id}:{kind.value}:{repetition}",
                        clip_id=clip.clip_id,
                        kind=kind,
                        repetition=repetition,
                        order_index=order,
                    )
                )
                order += 1
    return BenchmarkPlan(
        plan_id="plan-full",
        created_at=utc_now(),
        dataset_id=dataset.dataset_id,
        dataset_digest="sha256:" + "0" * 64,
        host_id="p-l-approved",
        profile_id="hypothetical-learned",
        profile_digest="sha256:" + "1" * 64,
        target_revision="v0.12-proposed",
        order_seed=7,
        planned_runs=runs,
    )


def good_memory() -> MemoryObservation:
    return MemoryObservation(
        status=EvidenceStatus.MEASURED,
        method=MemoryMethod.CGROUP_V2_MEMORY_PEAK,
        peak_bytes=3 * 1024**3,
        scope="application_group_cgroup",
    )


def passing_records(plan: BenchmarkPlan) -> list[RunRecord]:
    walls = {RunKind.WARM_FINAL: 40.0, RunKind.COLD_FINAL: 70.0, RunKind.WARM_PREVIEW: 8.0}
    return [
        RunRecord(
            run_id=run.run_id,
            plan_id=plan.plan_id,
            clip_id=run.clip_id,
            kind=run.kind,
            repetition=run.repetition,
            outcome=RunOutcome.SUCCEEDED,
            wall_seconds=walls[run.kind],
            output_hash="sha256:" + "3" * 64,
            memory=good_memory(),
            host_id=plan.host_id,
            profile_id=plan.profile_id,
            qualification_eligible_profile=True,
            exploratory=False,
        )
        for run in plan.planned_runs
    ]


def full_evidence(dataset: DatasetManifest) -> EvidenceBundle:
    reviews = [
        QualityReview(
            clip_id=clip.clip_id,
            reviewer_id=reviewer,
            identity_score=9,
            motion_score=8,
            any_dimension_zero=False,
            max_defect_severity=1,
            endpoint_check_passed=True,
            recorded_at=utc_now(),
        )
        for clip in dataset.clips
        for reviewer in ("reviewer-a", "reviewer-b")
    ]
    packs = [
        FreshInputPackRecord(
            pack_id=f"pack-{i}",
            active_preparation_seconds=200.0,
            automatic_preprocessing_seconds=12.0,
            used_prebuilt_rig_or_layers=False,
            used_accelerator_preparation=False,
            recorded_at=utc_now(),
        )
        for i in range(4)
    ]
    cases = [
        UnsupportedCaseRecord(
            case_id=f"case-{category}",
            category=category,
            rejected_before_synthesis=True,
            disposition="rejected with explicit redesign request",
            recorded_at=utc_now(),
        )
        for category in (
            "large_viewpoint_change",
            "newly_exposed_unseen_content",
            "scene_cut",
            "conflicting_anchor_timing",
        )
    ]
    return EvidenceBundle(
        quality_reviews=reviews,
        fresh_input_packs=packs,
        unsupported_cases=cases,
        continuous_workload=ContinuousWorkloadRecord(
            duration_minutes=20.0,
            throttling_observed_status=EvidenceStatus.MEASURED,
            throttling_observed=False,
            latency_limit_breached=False,
            memory_limit_breached=False,
            peak_memory=good_memory(),
        ),
        offline_rerun_status=EvidenceStatus.MEASURED,
        device_trace_status=EvidenceStatus.MEASURED,
    )


def evaluate(**overrides):
    dataset = overrides.pop("dataset", None) or locked_dataset()
    plan = overrides.pop("plan", None) or full_plan(dataset)
    records = overrides.pop("records", None)
    if records is None:
        records = passing_records(plan)
    evidence = overrides.pop("evidence", None) or full_evidence(dataset)
    host = overrides.pop("host", None) or approved_host()
    profile = overrides.pop("profile", None) or learned_profile()
    targets = overrides.pop("targets", None) or approved_targets()
    assert not overrides, f"unused overrides: {sorted(overrides)}"
    return evaluate_eligibility(
        plan=plan,
        dataset=dataset,
        host=host,
        profile=profile,
        targets=targets,
        records=records,
        evidence=evidence,
        summaries=distributions_for(plan, records),
    )


def codes(findings):
    return {f.code for f in findings if f.blocking}


# --- the control case ---------------------------------------------------------


def test_a_complete_eligible_passing_sample_qualifies():
    verdict, findings = evaluate()
    assert verdict is QualificationVerdict.QUALIFYING_PASS, sorted(codes(findings))
    assert not codes(findings)


# --- eligibility preconditions ------------------------------------------------


def test_the_fixture_adapter_can_never_qualify():
    from animalite.adapters.fixture import FIXTURE_PROFILE

    verdict, findings = evaluate(profile=FIXTURE_PROFILE)
    assert verdict is QualificationVerdict.NOT_ELIGIBLE
    assert "ELIG-PROFILE-NOT-LEARNED" in codes(findings)
    assert "ELIG-NO-LEARNED-TEMPORAL" in codes(findings)


def test_a_profile_cannot_declare_itself_eligible_without_a_learned_component():
    with pytest.raises(ValueError, match="learned_temporal_participation=False"):
        EngineProfile(
            profile_id="dishonest",
            display_name="dishonest",
            adapter_key="fixture-synthetic",
            engine_class=EngineClass.ML_ASSISTED,
            learned_temporal_participation=False,
            qualification_eligible=True,
            supported_tiers=[MotionTier.E3],
            supported_tasks=["x"],
            supported_endpoint_modes=[EndpointControlMode.DETERMINISTIC_STATE],
            supported_resolutions=[Resolution(width=640, height=360)],
            thread_budget=ThreadBudget(total_threads=4),
        )


def test_a_deterministic_profile_cannot_be_eligible():
    with pytest.raises(ValueError, match="deterministic"):
        EngineProfile(
            profile_id="deterministic-claiming-eligibility",
            display_name="x",
            adapter_key="fixture-synthetic",
            engine_class=EngineClass.DETERMINISTIC,
            learned_temporal_participation=True,
            qualification_eligible=True,
            supported_tiers=[MotionTier.E3],
            supported_tasks=["x"],
            supported_endpoint_modes=[EndpointControlMode.DETERMINISTIC_STATE],
            supported_resolutions=[Resolution(width=640, height=360)],
            thread_budget=ThreadBudget(total_threads=4),
        )


def test_an_unapproved_host_cannot_qualify():
    host = approved_host().model_copy(update={"approval": HostApproval()})
    verdict, findings = evaluate(host=host)
    assert verdict is QualificationVerdict.NOT_ELIGIBLE
    assert "ELIG-HOST-UNAPPROVED" in codes(findings)


def test_a_host_cannot_approve_itself():
    with pytest.raises(ValueError, match="cannot approve itself"):
        HostApproval(approved=True)


def test_unapproved_targets_cannot_qualify():
    verdict, findings = evaluate(targets=TargetSet())
    assert verdict is QualificationVerdict.NOT_ELIGIBLE
    assert "ELIG-TARGETS-UNAPPROVED" in codes(findings)


def test_an_unlocked_development_dataset_cannot_qualify():
    dataset = locked_dataset().model_copy(update={"purpose": "development", "locked": False})
    verdict, findings = evaluate(dataset=dataset)
    assert verdict is QualificationVerdict.NOT_ELIGIBLE
    assert "ELIG-DATASET-NOT-LOCKED" in codes(findings)


def test_the_sample_composition_must_be_four_per_category():
    dataset = locked_dataset()
    clips = list(dataset.clips)
    clips[0] = clips[0].model_copy(update={"category": "gesture_body"})
    verdict, findings = evaluate(dataset=dataset.model_copy(update={"clips": clips}))
    assert verdict is QualificationVerdict.NOT_ELIGIBLE
    assert "ELIG-DATASET-COMPOSITION" in codes(findings)


def test_at_least_two_clips_must_use_only_two_anchors():
    dataset = locked_dataset()
    clips = [c.model_copy(update={"anchor_count": 4}) for c in dataset.clips]
    verdict, findings = evaluate(dataset=dataset.model_copy(update={"clips": clips}))
    assert verdict is QualificationVerdict.NOT_ELIGIBLE
    assert "ELIG-DATASET-TWO-ANCHOR" in codes(findings)


# --- observation completeness -------------------------------------------------


def test_a_missing_observation_blocks_the_pass():
    dataset = locked_dataset()
    plan = full_plan(dataset)
    records = passing_records(plan)[:-1]  # one planned run never produced a record
    verdict, findings = evaluate(dataset=dataset, plan=plan, records=records)
    assert verdict is QualificationVerdict.QUALIFYING_FAIL
    assert "OBS-MISSING-RUNS" in codes(findings)


def test_deleting_a_failed_run_cannot_manufacture_a_pass():
    """The whole point: removing the weak case leaves a *missing* observation."""
    dataset = locked_dataset()
    plan = full_plan(dataset)
    records = passing_records(plan)
    # A run timed out. Keeping it fails the sample...
    with_failure = [
        r.model_copy(
            update={
                "outcome": RunOutcome.TIMEOUT,
                "wall_seconds": None,
                "output_hash": None,
                "failure": FailureRecord(
                    category=FailureCategory.TIMEOUT, message="exceeded the job timeout"
                ),
            }
        )
        if r.run_id == records[0].run_id
        else r
        for r in records
    ]
    verdict, findings = evaluate(dataset=dataset, plan=plan, records=with_failure)
    assert verdict is QualificationVerdict.QUALIFYING_FAIL
    assert "OBS-FAILED-RUNS" in codes(findings)

    # ...and deleting it fails the sample too, for a different reason.
    without = [r for r in with_failure if r.run_id != records[0].run_id]
    verdict, findings = evaluate(dataset=dataset, plan=plan, records=without)
    assert verdict is QualificationVerdict.QUALIFYING_FAIL
    assert "OBS-MISSING-RUNS" in codes(findings)


def test_p95_over_target_fails_the_sample():
    dataset = locked_dataset()
    plan = full_plan(dataset)
    records = [
        r.model_copy(update={"wall_seconds": 75.0}) if r.kind is RunKind.WARM_FINAL else r
        for r in passing_records(plan)
    ]
    verdict, findings = evaluate(dataset=dataset, plan=plan, records=records)
    assert verdict is QualificationVerdict.QUALIFYING_FAIL
    assert "OBS-P95-EXCEEDED" in codes(findings)


def test_one_slow_warm_run_breaches_the_per_run_maximum():
    dataset = locked_dataset()
    plan = full_plan(dataset)
    records = passing_records(plan)
    warm = next(i for i, r in enumerate(records) if r.kind is RunKind.WARM_FINAL)
    records[warm] = records[warm].model_copy(update={"wall_seconds": 91.0})
    verdict, findings = evaluate(dataset=dataset, plan=plan, records=records)
    assert verdict is QualificationVerdict.QUALIFYING_FAIL
    assert "OBS-MAX-EXCEEDED" in codes(findings)


def test_missing_memory_evidence_blocks_the_pass():
    dataset = locked_dataset()
    plan = full_plan(dataset)
    records = [
        r.model_copy(update={"memory": MemoryObservation.unavailable("not sampled")})
        for r in passing_records(plan)
    ]
    verdict, findings = evaluate(dataset=dataset, plan=plan, records=records)
    assert verdict is QualificationVerdict.QUALIFYING_FAIL
    assert "OBS-MEMORY-MISSING" in codes(findings)


def test_parent_only_memory_is_not_application_group_evidence():
    dataset = locked_dataset()
    plan = full_plan(dataset)
    parent_only = MemoryObservation(
        status=EvidenceStatus.MEASURED,
        method=MemoryMethod.PROC_VMHWM_PLUS_CHILD_MAXRSS,
        peak_bytes=1024,
        scope="parent_plus_reaped_children",
    )
    records = [r.model_copy(update={"memory": parent_only}) for r in passing_records(plan)]
    verdict, findings = evaluate(dataset=dataset, plan=plan, records=records)
    assert verdict is QualificationVerdict.QUALIFYING_FAIL
    assert "OBS-MEMORY-SCOPE" in codes(findings)


def test_an_unavailable_memory_observation_cannot_carry_a_value():
    with pytest.raises(ValueError, match="not a zero measurement"):
        MemoryObservation(status=EvidenceStatus.UNAVAILABLE, peak_bytes=0)


# --- human and AT-056 evidence ------------------------------------------------


def test_missing_quality_reviews_block_the_pass():
    dataset = locked_dataset()
    evidence = full_evidence(dataset).model_copy(update={"quality_reviews": []})
    verdict, findings = evaluate(dataset=dataset, evidence=evidence)
    assert verdict is QualificationVerdict.QUALIFYING_FAIL
    assert "QUAL-REVIEWERS-MISSING" in codes(findings)


def test_one_reviewer_is_not_enough():
    dataset = locked_dataset()
    evidence = full_evidence(dataset)
    single = [r for r in evidence.quality_reviews if r.reviewer_id == "reviewer-a"]
    verdict, findings = evaluate(
        dataset=dataset, evidence=evidence.model_copy(update={"quality_reviews": single})
    )
    assert verdict is QualificationVerdict.QUALIFYING_FAIL
    assert "QUAL-REVIEWERS-MISSING" in codes(findings)


def test_fast_runs_cannot_waive_a_quality_failure():
    dataset = locked_dataset()
    evidence = full_evidence(dataset)
    reviews = list(evidence.quality_reviews)
    reviews[0] = reviews[0].model_copy(update={"identity_score": 7})
    verdict, findings = evaluate(
        dataset=dataset, evidence=evidence.model_copy(update={"quality_reviews": reviews})
    )
    assert verdict is QualificationVerdict.QUALIFYING_FAIL
    assert "QUAL-SCORE-FAIL" in codes(findings)


def test_a_severity_two_defect_fails_the_clip():
    dataset = locked_dataset()
    evidence = full_evidence(dataset)
    reviews = list(evidence.quality_reviews)
    reviews[0] = reviews[0].model_copy(update={"max_defect_severity": 2})
    verdict, findings = evaluate(
        dataset=dataset, evidence=evidence.model_copy(update={"quality_reviews": reviews})
    )
    assert verdict is QualificationVerdict.QUALIFYING_FAIL
    assert "QUAL-SCORE-FAIL" in codes(findings)


def test_missing_fresh_input_packs_block_at056():
    dataset = locked_dataset()
    evidence = full_evidence(dataset).model_copy(update={"fresh_input_packs": []})
    _verdict, findings = evaluate(dataset=dataset, evidence=evidence)
    assert "AT056-FRESH-PACKS" in codes(findings)


def test_excess_preparation_effort_blocks_at056():
    dataset = locked_dataset()
    evidence = full_evidence(dataset)
    packs = list(evidence.fresh_input_packs)
    packs[0] = packs[0].model_copy(update={"active_preparation_seconds": 400.0})
    _verdict, findings = evaluate(
        dataset=dataset, evidence=evidence.model_copy(update={"fresh_input_packs": packs})
    )
    assert "AT056-PREP-EXCEEDED" in codes(findings)


def test_missing_unsupported_cases_block_at056():
    dataset = locked_dataset()
    evidence = full_evidence(dataset).model_copy(update={"unsupported_cases": []})
    _verdict, findings = evaluate(dataset=dataset, evidence=evidence)
    assert "AT056-UNSUPPORTED-CASES" in codes(findings)


def test_pending_offline_and_device_evidence_block_the_pass():
    dataset = locked_dataset()
    evidence = full_evidence(dataset).model_copy(
        update={
            "offline_rerun_status": EvidenceStatus.PENDING,
            "device_trace_status": EvidenceStatus.PENDING,
        }
    )
    _verdict, findings = evaluate(dataset=dataset, evidence=evidence)
    assert {"AT056-OFFLINE", "AT055-DEVICE-TRACE"} <= codes(findings)


def test_a_missing_continuous_workload_blocks_the_pass():
    dataset = locked_dataset()
    evidence = full_evidence(dataset).model_copy(update={"continuous_workload": None})
    _verdict, findings = evaluate(dataset=dataset, evidence=evidence)
    assert "OBS-CONTINUOUS-WORKLOAD" in codes(findings)


# --- report level -------------------------------------------------------------


def test_a_report_cannot_pass_while_carrying_blocking_findings(tmp_path):
    from animalite.contracts.benchmark import BenchmarkReport, EligibilityFinding

    with pytest.raises(ValueError, match="cannot be reported alongside blocking findings"):
        BenchmarkReport(
            plan_id="p",
            generated_at=utc_now(),
            dataset_id="d",
            dataset_purpose="qualification",
            host_id="h",
            host_approved=True,
            profile_id="x",
            profile_qualification_eligible=True,
            target_revision="v",
            targets_approved=True,
            verdict=QualificationVerdict.QUALIFYING_PASS,
            exploratory=False,
            label="pass",
            findings=[EligibilityFinding(code="X", blocking=True, message="m")],
        )


def test_an_exploratory_report_cannot_be_a_pass():
    from animalite.contracts.benchmark import BenchmarkReport

    with pytest.raises(ValueError, match="exploratory report cannot carry a qualifying pass"):
        BenchmarkReport(
            plan_id="p",
            generated_at=utc_now(),
            dataset_id="d",
            dataset_purpose="qualification",
            host_id="h",
            host_approved=True,
            profile_id="x",
            profile_qualification_eligible=True,
            target_revision="v",
            targets_approved=True,
            verdict=QualificationVerdict.QUALIFYING_PASS,
            exploratory=True,
            label="pass",
        )


def test_a_tampered_ledger_blocks_the_pass(tmp_path):
    dataset = locked_dataset()
    plan = full_plan(dataset)
    ledger = RunLedger(tmp_path / "ledger")
    ledger.write_plan(plan)
    for record in passing_records(plan):
        ledger.append(record)

    lines = ledger.runs_path.read_text().splitlines()
    ledger.runs_path.write_text("\n".join(lines[:-1]) + "\n")

    report = build_report(
        plan=plan,
        dataset=dataset,
        host=approved_host(),
        profile=learned_profile(),
        targets=approved_targets(),
        ledger=ledger,
        evidence=full_evidence(dataset),
    )
    assert report.verdict is QualificationVerdict.QUALIFYING_FAIL
    assert not report.ledger_verified
    assert "LEDGER-INTEGRITY" in {f.code for f in report.blocking_findings}


def test_the_fixture_report_is_labelled_exploratory(tmp_path):
    from animalite.adapters.fixture import FIXTURE_PROFILE

    dataset = locked_dataset()
    plan = full_plan(dataset)
    ledger = RunLedger(tmp_path / "ledger")
    ledger.write_plan(plan)
    for record in passing_records(plan):
        ledger.append(record)
    report = build_report(
        plan=plan,
        dataset=dataset,
        host=approved_host(),
        profile=FIXTURE_PROFILE,
        targets=approved_targets(),
        ledger=ledger,
        evidence=full_evidence(dataset),
    )
    assert report.verdict is QualificationVerdict.NOT_ELIGIBLE
    assert report.exploratory
    assert "NOT QUALIFICATION EVIDENCE" in report.label
