"""Qualification eligibility evaluator.

Handoff section 13: "A fixture adapter, unapproved host or missing
quality/device/memory evidence cannot receive a model-qualification pass."

The evaluator answers one question -- *may a section 12.0 pass be reported?* --
and it answers "no" by default. Reaching
:attr:`~animalite.contracts.enums.QualificationVerdict.QUALIFYING_PASS` requires
every precondition below to hold. Anything else yields ``NOT_ELIGIBLE`` (with the
report marked exploratory) or ``QUALIFYING_FAIL`` when the sample was eligible
but did not meet the contract.
"""

from __future__ import annotations

from animalite.bench.ledger import RunLedger
from animalite.bench.stats import maximum, median, nearest_rank_percentile
from animalite.contracts.benchmark import (
    QUALIFICATION_CATEGORIES,
    BenchmarkPlan,
    BenchmarkReport,
    DatasetManifest,
    DistributionSummary,
    EligibilityFinding,
    EvidenceBundle,
    HostRecord,
    RunRecord,
    TargetSet,
)
from animalite.contracts.enums import (
    EvidenceStatus,
    MemoryMethod,
    QualificationVerdict,
    RunKind,
    RunOutcome,
)
from animalite.contracts.job import EnvironmentRecord
from animalite.contracts.profile import EngineProfile
from animalite.core.logging import utc_now

__all__ = ["build_report", "distributions_for", "evaluate_eligibility"]

_REQUIRED_KINDS = (RunKind.WARM_FINAL, RunKind.COLD_FINAL, RunKind.WARM_PREVIEW)

_EXPLORATORY_LABEL = (
    "EXPLORATORY -- NOT QUALIFICATION EVIDENCE. This report does not establish any "
    "section 12.0 result and does not discharge AT-055 or AT-056."
)


def _finding(
    code: str, message: str, refs: list[str], *, blocking: bool = True
) -> EligibilityFinding:
    return EligibilityFinding(code=code, blocking=blocking, message=message, requirement_refs=refs)


def distributions_for(plan: BenchmarkPlan, records: list[RunRecord]) -> list[DistributionSummary]:
    """Per-run-kind statistics, counting failures and missing runs explicitly."""
    summaries: list[DistributionSummary] = []
    by_run_id = {r.run_id: r for r in records}
    for kind in RunKind:
        planned = [p for p in plan.planned_runs if p.kind is kind]
        if not planned:
            continue
        found = [by_run_id[p.run_id] for p in planned if p.run_id in by_run_id]
        succeeded = [r for r in found if r.outcome is RunOutcome.SUCCEEDED]
        observations = sorted(r.wall_seconds for r in succeeded if r.wall_seconds is not None)
        percentile = nearest_rank_percentile(observations)
        summaries.append(
            DistributionSummary(
                kind=kind,
                n_planned=len(planned),
                n_recorded=len(found),
                n_succeeded=len(succeeded),
                n_failed=len(found) - len(succeeded),
                n_missing=len(planned) - len(found),
                observations=observations,
                median_seconds=median(observations),
                p95_seconds=percentile[0] if percentile else None,
                p95_sorted_index=percentile[1] if percentile else None,
                maximum_seconds=maximum(observations),
                minimum_seconds=min(observations) if observations else None,
                complete=(len(succeeded) == len(planned) and len(planned) > 0),
            )
        )
    return summaries


def _check_eligibility(
    *,
    plan: BenchmarkPlan,
    dataset: DatasetManifest,
    host: HostRecord,
    profile: EngineProfile,
    targets: TargetSet,
) -> list[EligibilityFinding]:
    """Preconditions that must hold before *any* measurement can qualify."""
    findings: list[EligibilityFinding] = []

    if not profile.qualification_eligible:
        findings.append(
            _finding(
                "ELIG-PROFILE-NOT-LEARNED",
                f"engine profile {profile.profile_id!r} is not qualification-eligible: "
                f"{profile.non_qualifying_reason}",
                ["MR-018", "AT-055", "CR-025"],
            )
        )
    if not profile.learned_temporal_participation:
        findings.append(
            _finding(
                "ELIG-NO-LEARNED-TEMPORAL",
                "the profile declares no learned component participating in temporal "
                "synthesis; cross-fades, camera transforms and repeated source frames "
                "cannot satisfy MR-018",
                ["MR-018"],
            )
        )
    if not profile.cpu_only_guaranteed:
        findings.append(
            _finding(
                "ELIG-CPU-NOT-GUARANTEED",
                "the profile does not guarantee CPU-only execution",
                ["MR-016", "MR-017", "NFR-028"],
            )
        )

    if not host.approval.approved:
        findings.append(
            _finding(
                "ELIG-HOST-UNAPPROVED",
                f"host {host.host_id!r} has no D-02 approval record; timings on an "
                "unapproved host are exploratory. Core count alone is not hardware "
                "equivalence.",
                ["D-02", "SM-19", "CR-025"],
            )
        )
    if host.inventory is None:
        findings.append(
            _finding(
                "ELIG-HOST-NO-INVENTORY",
                f"host {host.host_id!r} carries no recorded inventory",
                ["MR-013", "NFR-028"],
            )
        )
    if host.power_policy is None or host.thermal_policy is None:
        findings.append(
            _finding(
                "ELIG-HOST-NO-POWER-POLICY",
                "the sustained power/thermal policy is not recorded for this host",
                ["D-02", "section 12.0"],
            )
        )

    if not targets.approved:
        findings.append(
            _finding(
                "ELIG-TARGETS-UNAPPROVED",
                f"target revision {targets.target_revision!r} is not approved; the "
                "section 12.0 limits remain proposed engineering targets",
                ["D-02", "section 12.0"],
            )
        )

    if dataset.purpose != "qualification" or not dataset.locked:
        findings.append(
            _finding(
                "ELIG-DATASET-NOT-LOCKED",
                f"dataset {dataset.dataset_id!r} has purpose {dataset.purpose!r} and "
                f"locked={dataset.locked}; qualification needs the frozen 12-clip sample",
                ["section 12.0", "AT-055"],
            )
        )
    counts = dataset.category_counts
    if counts != QUALIFICATION_CATEGORIES:
        findings.append(
            _finding(
                "ELIG-DATASET-COMPOSITION",
                f"dataset composition {counts} does not match the required "
                f"{QUALIFICATION_CATEGORIES}",
                ["section 12.0"],
            )
        )
    if dataset.two_anchor_clip_count < 2:
        findings.append(
            _finding(
                "ELIG-DATASET-TWO-ANCHOR",
                f"only {dataset.two_anchor_clip_count} clip(s) use exactly two anchors; "
                "at least two are required",
                ["section 12.0"],
            )
        )

    expected_ids = {clip.clip_id for clip in dataset.clips}
    planned_ids = {run.clip_id for run in plan.planned_runs}
    if expected_ids != planned_ids:
        findings.append(
            _finding(
                "ELIG-PLAN-COVERAGE",
                "the plan does not schedule exactly the dataset's clips; missing "
                f"{sorted(expected_ids - planned_ids)}, extra {sorted(planned_ids - expected_ids)}",
                ["section 12.0", "AT-055"],
            )
        )
    if plan.batch_size != 1:
        findings.append(
            _finding(
                "ELIG-BATCH-SIZE",
                f"batch size {plan.batch_size} != 1; qualification runs at batch size one",
                ["section 12.0"],
            )
        )
    for attribute, required, label in (
        ("warm_repetitions_per_clip", 3, "warm final"),
        ("cold_repetitions_per_clip", 1, "process-cold final"),
        ("preview_repetitions_per_clip", 3, "warm preview"),
    ):
        actual = getattr(plan, attribute)
        if actual != required:
            findings.append(
                _finding(
                    "ELIG-REPETITIONS",
                    f"{label} repetitions per clip is {actual}; the locked protocol "
                    f"requires {required}",
                    ["section 12.0", "DEC-0006"],
                )
            )
    return findings


def _check_observations(
    *,
    summaries: list[DistributionSummary],
    records: list[RunRecord],
    targets: TargetSet,
) -> list[EligibilityFinding]:
    """Completeness and threshold checks over the recorded runs."""
    findings: list[EligibilityFinding] = []
    by_kind = {s.kind: s for s in summaries}

    for kind in _REQUIRED_KINDS:
        summary = by_kind.get(kind)
        if summary is None:
            findings.append(
                _finding(
                    "OBS-KIND-NOT-PLANNED",
                    f"no {kind.value} runs were planned",
                    ["section 12.0", "AT-055"],
                )
            )
            continue
        if summary.n_missing:
            findings.append(
                _finding(
                    "OBS-MISSING-RUNS",
                    f"{summary.n_missing} of {summary.n_planned} {kind.value} runs have "
                    "no record; a missing required observation fails the sample",
                    ["section 12.0", "NFR-028"],
                )
            )
        if summary.n_failed:
            findings.append(
                _finding(
                    "OBS-FAILED-RUNS",
                    f"{summary.n_failed} {kind.value} run(s) failed, timed out or "
                    "produced invalid output; they remain in the ledger and fail the sample",
                    ["section 12.0", "AT-055"],
                )
            )

    thresholds = (
        (RunKind.WARM_PREVIEW, targets.warm_preview_p95_seconds, None, "warm preview"),
        (
            RunKind.WARM_FINAL,
            targets.warm_final_p95_seconds,
            targets.warm_final_max_seconds,
            "warm final",
        ),
        (
            RunKind.COLD_FINAL,
            targets.cold_final_p95_seconds,
            targets.cold_final_max_seconds,
            "process-cold final",
        ),
    )
    for kind, p95_limit, max_limit, label in thresholds:
        summary = by_kind.get(kind)
        if summary is None or summary.p95_seconds is None:
            continue
        if summary.p95_seconds > p95_limit:
            findings.append(
                _finding(
                    "OBS-P95-EXCEEDED",
                    f"{label} p95 {summary.p95_seconds:.3f}s exceeds the "
                    f"{p95_limit:.0f}s target (nearest-rank index "
                    f"{summary.p95_sorted_index} of n={summary.n_succeeded})",
                    ["section 12.0", "SM-19"],
                )
            )
        breached_max = (
            max_limit is not None
            and summary.maximum_seconds is not None
            and summary.maximum_seconds > max_limit
        )
        if breached_max:
            findings.append(
                _finding(
                    "OBS-MAX-EXCEEDED",
                    f"{label} maximum {summary.maximum_seconds:.3f}s exceeds the "
                    f"per-run limit of {max_limit:.0f}s",
                    ["section 12.0"],
                )
            )

    memory_seen = False
    for record in records:
        if record.outcome is not RunOutcome.SUCCEEDED:
            continue
        memory = record.memory
        if memory.status is not EvidenceStatus.MEASURED:
            findings.append(
                _finding(
                    "OBS-MEMORY-MISSING",
                    f"run {record.run_id} has no measured peak-memory observation "
                    f"(status {memory.status.value}); an unavailable measurement is not "
                    "a zero measurement",
                    ["section 12.0", "MR-013", "NFR-028"],
                )
            )
            continue
        memory_seen = True
        if memory.method is not MemoryMethod.CGROUP_V2_MEMORY_PEAK:
            findings.append(
                _finding(
                    "OBS-MEMORY-SCOPE",
                    f"run {record.run_id} measured memory with {memory.method.value}, "
                    "which does not give a simultaneous application-group peak across "
                    "app, worker and encoder",
                    ["section 12.0", "MR-013"],
                )
            )
        over_limit = (
            memory.peak_bytes is not None
            and memory.peak_bytes > targets.peak_application_memory_bytes
        )
        if over_limit:
            findings.append(
                _finding(
                    "OBS-MEMORY-EXCEEDED",
                    f"run {record.run_id} peak {memory.peak_bytes} bytes exceeds the "
                    f"{targets.peak_application_memory_bytes} byte limit",
                    ["section 12.0"],
                )
            )
    if not memory_seen:
        findings.append(
            _finding(
                "OBS-MEMORY-NONE",
                "no run carries a measured peak-memory observation",
                ["section 12.0", "MR-013"],
            )
        )
    return findings


def _check_evidence(
    *, dataset: DatasetManifest, evidence: EvidenceBundle, targets: TargetSet
) -> list[EligibilityFinding]:
    """Quality, fresh-input, unsupported-case and offline/device evidence."""
    findings: list[EligibilityFinding] = []
    clip_ids = [clip.clip_id for clip in dataset.clips]

    reviewers_by_clip: dict[str, set[str]] = {}
    for review in evidence.quality_reviews:
        reviewers_by_clip.setdefault(review.clip_id, set()).add(review.reviewer_id)
    for clip_id in clip_ids:
        reviewers = reviewers_by_clip.get(clip_id, set())
        if len(reviewers) < 2:
            findings.append(
                _finding(
                    "QUAL-REVIEWERS-MISSING",
                    f"clip {clip_id} has {len(reviewers)} independent reviewer(s); two "
                    "are required and latency cannot waive quality",
                    ["section 12.0", "section 15.2", "CR-012"],
                )
            )
    for review in evidence.quality_reviews:
        if not review.passes:
            findings.append(
                _finding(
                    "QUAL-SCORE-FAIL",
                    f"clip {review.clip_id} reviewer {review.reviewer_id}: identity "
                    f"{review.identity_score}/10, motion {review.motion_score}/10, "
                    f"zero dimension={review.any_dimension_zero}, max defect severity "
                    f"{review.max_defect_severity}, endpoint "
                    f"{'pass' if review.endpoint_check_passed else 'fail'}",
                    ["section 12.0", "section 15.2"],
                )
            )

    if len(evidence.fresh_input_packs) < 4:
        findings.append(
            _finding(
                "AT056-FRESH-PACKS",
                f"{len(evidence.fresh_input_packs)} fresh input pack(s) recorded; "
                "AT-056 requires four",
                ["AT-056", "section 12.0"],
            )
        )
    for pack in evidence.fresh_input_packs:
        if pack.active_preparation_seconds > 300.0:
            findings.append(
                _finding(
                    "AT056-PREP-EXCEEDED",
                    f"pack {pack.pack_id} used {pack.active_preparation_seconds:.0f}s "
                    "active preparation; the limit is 300s (5 minutes)",
                    ["AT-056", "section 12.0"],
                )
            )
        if pack.automatic_preprocessing_seconds > 30.0:
            findings.append(
                _finding(
                    "AT056-PREPROCESS-EXCEEDED",
                    f"pack {pack.pack_id} used "
                    f"{pack.automatic_preprocessing_seconds:.1f}s automatic local "
                    "preprocessing; the limit is 30s",
                    ["AT-056", "section 12.0"],
                )
            )
        if pack.used_prebuilt_rig_or_layers or pack.used_accelerator_preparation:
            findings.append(
                _finding(
                    "AT056-PREP-DISALLOWED",
                    f"pack {pack.pack_id} used a prebuilt rig/layers or accelerator "
                    "preparation, which AT-056 excludes",
                    ["AT-056"],
                )
            )

    required_cases = {
        "large_viewpoint_change",
        "newly_exposed_unseen_content",
        "scene_cut",
        "conflicting_anchor_timing",
    }
    seen_cases = {case.category for case in evidence.unsupported_cases}
    if not required_cases.issubset(seen_cases):
        findings.append(
            _finding(
                "AT056-UNSUPPORTED-CASES",
                f"unsupported-case categories not exercised: {sorted(required_cases - seen_cases)}",
                ["AT-056", "section 12.0", "MR-018"],
            )
        )
    for case in evidence.unsupported_cases:
        if not case.rejected_before_synthesis:
            findings.append(
                _finding(
                    "AT056-CASE-NOT-REJECTED",
                    f"unsupported case {case.case_id} was not rejected or routed to "
                    "redesign before synthesis",
                    ["AT-056", "MR-010", "MR-018"],
                )
            )

    workload = evidence.continuous_workload
    if workload is None:
        findings.append(
            _finding(
                "OBS-CONTINUOUS-WORKLOAD",
                f"no continuous {targets.continuous_workload_minutes}-minute workload "
                "record with thermal/power observations",
                ["section 12.0"],
            )
        )
    elif workload.duration_minutes < targets.continuous_workload_minutes:
        findings.append(
            _finding(
                "OBS-CONTINUOUS-SHORT",
                f"continuous workload ran {workload.duration_minutes:.1f} minutes; "
                f"{targets.continuous_workload_minutes} are required",
                ["section 12.0"],
            )
        )

    if evidence.offline_rerun_status is not EvidenceStatus.MEASURED:
        findings.append(
            _finding(
                "AT056-OFFLINE",
                f"offline rerun evidence is {evidence.offline_rerun_status.value}",
                ["AT-056", "MR-015", "NFR-008"],
            )
        )
    if evidence.device_trace_status is not EvidenceStatus.MEASURED:
        findings.append(
            _finding(
                "AT055-DEVICE-TRACE",
                f"runtime/device trace evidence is {evidence.device_trace_status.value}; "
                "CPU-only execution is not evidenced",
                ["AT-055", "AT-056", "MR-015", "NFR-028"],
            )
        )
    return findings


def evaluate_eligibility(
    *,
    plan: BenchmarkPlan,
    dataset: DatasetManifest,
    host: HostRecord,
    profile: EngineProfile,
    targets: TargetSet,
    records: list[RunRecord],
    evidence: EvidenceBundle,
    summaries: list[DistributionSummary],
    ledger_problems: list[str] | None = None,
) -> tuple[QualificationVerdict, list[EligibilityFinding]]:
    """Return the verdict and every finding behind it."""
    eligibility = _check_eligibility(
        plan=plan, dataset=dataset, host=host, profile=profile, targets=targets
    )
    findings = list(eligibility)
    findings.extend(_check_observations(summaries=summaries, records=records, targets=targets))
    findings.extend(_check_evidence(dataset=dataset, evidence=evidence, targets=targets))

    for problem in ledger_problems or []:
        findings.append(
            _finding(
                "LEDGER-INTEGRITY",
                f"run ledger integrity problem: {problem}",
                ["section 12.0", "NFR-003", "NFR-013"],
            )
        )

    if eligibility:
        # Not eligible to be judged at all: the sample could never qualify.
        return QualificationVerdict.NOT_ELIGIBLE, findings
    if any(f.blocking for f in findings):
        return QualificationVerdict.QUALIFYING_FAIL, findings
    return QualificationVerdict.QUALIFYING_PASS, findings


def build_report(
    *,
    plan: BenchmarkPlan,
    dataset: DatasetManifest,
    host: HostRecord,
    profile: EngineProfile,
    targets: TargetSet,
    ledger: RunLedger,
    evidence: EvidenceBundle | None = None,
    environment: EnvironmentRecord | None = None,
) -> BenchmarkReport:
    """Generate the benchmark report, exploratory unless everything qualifies."""
    resolved_evidence = evidence if evidence is not None else EvidenceBundle()
    verification = ledger.verify(plan)
    records = ledger.records()
    summaries = distributions_for(plan, records)
    verdict, findings = evaluate_eligibility(
        plan=plan,
        dataset=dataset,
        host=host,
        profile=profile,
        targets=targets,
        records=records,
        evidence=resolved_evidence,
        summaries=summaries,
        ledger_problems=verification.problems,
    )
    exploratory = verdict is not QualificationVerdict.QUALIFYING_PASS
    if verdict is QualificationVerdict.QUALIFYING_PASS:
        label = (
            "QUALIFYING PASS -- every section 12.0 precondition, observation and "
            "quality condition was satisfied on the approved host."
        )
    elif verdict is QualificationVerdict.QUALIFYING_FAIL:
        label = (
            "QUALIFYING FAIL -- the sample was eligible but did not meet the section "
            "12.0 contract. Failed and missing runs are retained in the ledger."
        )
    else:
        label = _EXPLORATORY_LABEL

    return BenchmarkReport(
        plan_id=plan.plan_id,
        generated_at=utc_now(),
        dataset_id=dataset.dataset_id,
        dataset_purpose=dataset.purpose,
        host_id=host.host_id,
        host_approved=host.approval.approved,
        profile_id=profile.profile_id,
        profile_qualification_eligible=profile.qualification_eligible,
        target_revision=targets.target_revision,
        targets_approved=targets.approved,
        verdict=verdict,
        exploratory=exploratory,
        label=label,
        distributions=summaries,
        findings=findings,
        ledger_digest=verification.head_digest,
        ledger_verified=verification.ok,
        environment=environment,
    )
