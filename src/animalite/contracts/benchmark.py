"""Benchmark plan, ledger and evidence contracts (section 12.0, AT-055/AT-056).

Design rule for this module: **absent evidence is representable and blocking.**
Every evidence bundle below defaults to empty, and the evaluator treats empty as
"missing observation", never as "nothing went wrong".
"""

from __future__ import annotations

from pydantic import Field, model_validator

from animalite.contracts.base import Contract, Document
from animalite.contracts.enums import (
    EvidenceStatus,
    QualificationVerdict,
    RunKind,
    RunOutcome,
)
from animalite.contracts.host import HostApproval, HostInventory
from animalite.contracts.job import EnvironmentRecord, FailureRecord, ProcessInstance
from animalite.contracts.media import FrameAccounting
from animalite.contracts.results import MemoryObservation, StageTiming

__all__ = [
    "QUALIFICATION_CATEGORIES",
    "BenchmarkPlan",
    "BenchmarkReport",
    "ColdProcessEvidence",
    "ContinuousWorkloadRecord",
    "DatasetClip",
    "DatasetManifest",
    "DistributionSummary",
    "EligibilityFinding",
    "EvidenceBundle",
    "FreshInputPackRecord",
    "HostRecord",
    "PlannedRun",
    "QualityReview",
    "RunRecord",
    "TargetSet",
    "UnsupportedCaseRecord",
]

#: Section 12.0 sample composition: four clips in each category.
QUALIFICATION_CATEGORIES: dict[str, int] = {
    "face_reaction": 4,
    "gesture_body": 4,
    "cloth_hair_overlap": 4,
}


class DatasetClip(Contract):
    clip_id: str = Field(min_length=1)
    category: str
    anchor_count: int = Field(ge=2, le=4)
    anchor_manifest_path: str
    animation_frame_count: int = Field(default=72, ge=2)
    intended_action: str = ""
    anchor_hashes: list[str] = Field(default_factory=list)


class DatasetManifest(Document):
    """A benchmark dataset. ``purpose`` decides whether it can qualify anything."""

    dataset_id: str = Field(min_length=1)
    revision: int = Field(default=1, ge=1)
    purpose: str = Field(default="development", pattern="^(development|qualification)$")
    locked: bool = False
    clips: list[DatasetClip] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @property
    def category_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for clip in self.clips:
            counts[clip.category] = counts.get(clip.category, 0) + 1
        return counts

    @property
    def two_anchor_clip_count(self) -> int:
        return sum(1 for clip in self.clips if clip.anchor_count == 2)


class HostRecord(Document):
    """A named benchmark host, its recorded inventory and its approval status."""

    host_id: str = Field(min_length=1)
    profile_envelope: str = "P-L"
    approval: HostApproval = HostApproval()
    inventory: HostInventory | None = None
    power_policy: str | None = None
    thermal_policy: str | None = None
    notes: list[str] = Field(default_factory=list)


class TargetSet(Document):
    """Section 12.0 proposed limits. ``approved`` is False until D-02 signs them."""

    target_revision: str = "v0.12-proposed"
    approved: bool = False
    approval_decision_id: str | None = None
    warm_preview_p95_seconds: float = 15.0
    warm_final_p95_seconds: float = 60.0
    warm_final_max_seconds: float = 90.0
    cold_final_p95_seconds: float = 90.0
    cold_final_max_seconds: float = 120.0
    peak_application_memory_bytes: int = 4 * 1024**3
    continuous_workload_minutes: int = 20
    status_note: str = (
        "Proposed engineering acceptance targets awaiting D-02 approval. The "
        "requirements document contains no P-L measurements."
    )

    @model_validator(mode="after")
    def _check(self) -> TargetSet:
        if self.approved and not self.approval_decision_id:
            raise ValueError("approved targets require approval_decision_id (D-02)")
        return self


class PlannedRun(Contract):
    """One run declared *before* timing, so a missing result is detectable."""

    run_id: str = Field(min_length=1)
    clip_id: str
    kind: RunKind
    repetition: int = Field(ge=1)
    order_index: int = Field(ge=0)


class BenchmarkPlan(Document):
    """The complete run schedule, fixed before any timing starts."""

    plan_id: str = Field(min_length=1)
    created_at: str
    dataset_id: str
    dataset_digest: str
    host_id: str
    profile_id: str
    profile_digest: str
    target_revision: str
    order_seed: int
    batch_size: int = Field(default=1, ge=1)
    warm_repetitions_per_clip: int = Field(default=3, ge=0)
    cold_repetitions_per_clip: int = Field(default=1, ge=0)
    preview_repetitions_per_clip: int = Field(default=3, ge=0)
    planned_runs: list[PlannedRun] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_unique(self) -> BenchmarkPlan:
        ids = [r.run_id for r in self.planned_runs]
        if len(set(ids)) != len(ids):
            raise ValueError("planned run_id values must be unique")
        return self

    def run_ids(self) -> set[str]:
        return {r.run_id for r in self.planned_runs}


class ColdProcessEvidence(Contract):
    """Evidence that a process-cold run really ran in a new process.

    Reconstructing the service inside the same interpreter leaves imports,
    native initialisation and any resident adapter state warm, so it cannot be
    called process-cold. Recording the child identity makes the claim checkable
    instead of asserted. ``os_file_cache_cleared`` is recorded as False because
    section 12.0 permits a warm OS cache but requires it to be disclosed.
    """

    child_pid: int | None = None
    parent_pid: int | None = None
    interpreter: str | None = None
    argv: list[str] = Field(default_factory=list)
    os_file_cache_cleared: bool = False
    #: The child's own report of its process instance, written at startup before
    #: any work. A pid is reused; ``(boot_id, pid, start_ticks)`` is not, so this
    #: is what makes "a genuinely new process" checkable across two cold runs.
    child_instance: ProcessInstance | None = None
    parent_instance: ProcessInstance | None = None
    #: Process groups still alive after the child was torn down. Non-empty means
    #: the cold run leaked a process, and it is recorded rather than assumed away.
    child_survivor_groups: list[int] = Field(default_factory=list)

    @property
    def is_distinct_process(self) -> bool:
        """True only when child and parent are provably different instances."""
        if self.child_instance is None or self.parent_instance is None:
            return False
        if not self.child_instance.is_identified:
            return False
        return self.child_instance.instance_key != self.parent_instance.instance_key

    notes: list[str] = Field(
        default_factory=lambda: [
            "Cold timing starts before the child interpreter is launched, so "
            "Python startup, imports, tool discovery and service/adapter "
            "construction are inside the boundary.",
            "OS file cache is not cleared: this is process-cold, not disk-cold.",
        ]
    )


class RunRecord(Document):
    """One executed (or attempted) benchmark run.

    A run with ``outcome != succeeded`` carries ``wall_seconds = None``: a failed
    run has no valid latency observation and must never contribute one.
    """

    run_id: str = Field(min_length=1)
    plan_id: str
    clip_id: str
    kind: RunKind
    repetition: int = Field(ge=1)
    outcome: RunOutcome
    attempt_id: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    wall_seconds: float | None = Field(default=None, ge=0.0)
    stages: list[StageTiming] = Field(default_factory=list)
    frame_accounting: FrameAccounting | None = None
    memory: MemoryObservation = MemoryObservation.unavailable("not sampled")
    output_hash: str | None = None
    failure: FailureRecord | None = None
    environment: EnvironmentRecord | None = None
    host_id: str
    profile_id: str
    qualification_eligible_profile: bool = False
    exploratory: bool = True
    cold_process_evidence: ColdProcessEvidence | None = None
    #: How long a failed or timed-out run took before it failed. Deliberately a
    #: separate field from ``wall_seconds``: failure latency is diagnostic, and
    #: must never be aggregated as if it were a successful observation.
    failure_elapsed_seconds: float | None = Field(default=None, ge=0.0)
    #: Process groups still alive after this run tore its children down. Copied
    #: from the attempt so the cleanup failure is visible in the ledger rather
    #: than only in the attempt directory.
    cleanup_survivor_groups: list[int] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> RunRecord:
        if self.outcome is RunOutcome.SUCCEEDED:
            if self.wall_seconds is None:
                raise ValueError("a succeeded run must carry wall_seconds")
            if self.output_hash is None:
                raise ValueError("a succeeded run must carry the output hash")
        elif self.wall_seconds is not None:
            raise ValueError(
                f"outcome {self.outcome.value!r} must not carry wall_seconds; a "
                "non-succeeding run contributes no latency observation"
            )
        if self.outcome is RunOutcome.SUCCEEDED and self.failure_elapsed_seconds is not None:
            raise ValueError(
                "a succeeded run must not carry failure_elapsed_seconds; its timing "
                "belongs in wall_seconds"
            )
        if self.outcome is RunOutcome.SUCCEEDED and self.cleanup_survivor_groups:
            raise ValueError(
                f"a succeeded run must not carry surviving process groups "
                f"{self.cleanup_survivor_groups}; a leaked process is a cleanup "
                "failure, not a clean run"
            )
        return self


class DistributionSummary(Contract):
    """Reported statistics for one run kind. ``observations`` is the raw list."""

    kind: RunKind
    n_planned: int = Field(ge=0)
    n_recorded: int = Field(ge=0)
    n_succeeded: int = Field(ge=0)
    n_failed: int = Field(ge=0)
    n_missing: int = Field(ge=0)
    observations: list[float] = Field(default_factory=list)
    median_seconds: float | None = None
    p95_seconds: float | None = None
    p95_sorted_index: int | None = None
    maximum_seconds: float | None = None
    minimum_seconds: float | None = None
    complete: bool = False


class QualityReview(Document):
    """One reviewer's section 15.2 scores for one clip."""

    clip_id: str
    reviewer_id: str
    identity_score: int = Field(ge=0, le=10)
    motion_score: int = Field(ge=0, le=10)
    any_dimension_zero: bool
    max_defect_severity: int = Field(ge=0, le=3)
    endpoint_check_passed: bool
    recorded_at: str
    notes: str = ""

    @property
    def passes(self) -> bool:
        return (
            self.identity_score >= 8
            and self.motion_score >= 8
            and not self.any_dimension_zero
            and self.max_defect_severity < 2
            and self.endpoint_check_passed
        )


class FreshInputPackRecord(Document):
    """AT-056 fresh-input pack: active preparation and automatic preprocessing."""

    pack_id: str
    active_preparation_seconds: float = Field(ge=0.0)
    automatic_preprocessing_seconds: float = Field(ge=0.0)
    used_prebuilt_rig_or_layers: bool
    used_accelerator_preparation: bool
    recorded_at: str


class UnsupportedCaseRecord(Document):
    """One of the four locked out-of-scope cases in section 12.0."""

    case_id: str
    category: str
    rejected_before_synthesis: bool
    disposition: str
    validation_codes: list[str] = Field(default_factory=list)
    recorded_at: str


class ContinuousWorkloadRecord(Document):
    """The continuous 20-minute workload and its thermal/power observations.

    Duration alone is not the test. Section 12.0 asks for thermal/power
    throttling to be reported *and* for whether latency or memory limits were
    breached; a 20-minute run that breached both is a failure, not a pass. The
    breach fields are therefore tri-state: ``None`` means "not determined",
    which blocks, rather than silently reading as "fine".
    """

    duration_minutes: float = Field(ge=0.0)
    throttling_observed_status: EvidenceStatus = EvidenceStatus.PENDING
    throttling_observed: bool | None = None
    latency_limit_breached: bool | None = None
    memory_limit_breached: bool | None = None
    peak_memory: MemoryObservation = MemoryObservation.unavailable("not sampled")
    #: Section 12.0 "no swap reliance". PENDING/None blocks; it is not assumed.
    swap_reliance_status: EvidenceStatus = EvidenceStatus.PENDING
    swap_used_bytes: int | None = Field(default=None, ge=0)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_swap(self) -> ContinuousWorkloadRecord:
        if self.swap_reliance_status is EvidenceStatus.MEASURED:
            if self.swap_used_bytes is None:
                raise ValueError("swap_reliance_status 'measured' requires swap_used_bytes")
        elif self.swap_used_bytes is not None:
            raise ValueError(
                f"swap_reliance_status {self.swap_reliance_status.value!r} must not carry "
                "swap_used_bytes; an unavailable observation is not a measured zero"
            )
        return self


class EvidenceBundle(Document):
    """Non-timing evidence required by section 12.0. Empty means missing."""

    quality_reviews: list[QualityReview] = Field(default_factory=list)
    fresh_input_packs: list[FreshInputPackRecord] = Field(default_factory=list)
    unsupported_cases: list[UnsupportedCaseRecord] = Field(default_factory=list)
    continuous_workload: ContinuousWorkloadRecord | None = None
    offline_rerun_status: EvidenceStatus = EvidenceStatus.PENDING
    device_trace_status: EvidenceStatus = EvidenceStatus.PENDING
    notes: list[str] = Field(default_factory=list)


class EligibilityFinding(Contract):
    """One reason a qualification verdict is or is not available."""

    code: str
    blocking: bool
    message: str
    requirement_refs: list[str] = Field(default_factory=list)


class BenchmarkReport(Document):
    """The generated summary. Always safe to publish; never silently a pass."""

    plan_id: str
    generated_at: str
    dataset_id: str
    dataset_purpose: str
    host_id: str
    host_approved: bool
    profile_id: str
    profile_qualification_eligible: bool
    target_revision: str
    targets_approved: bool

    verdict: QualificationVerdict
    exploratory: bool
    label: str

    distributions: list[DistributionSummary] = Field(default_factory=list)
    findings: list[EligibilityFinding] = Field(default_factory=list)
    ledger_digest: str | None = None
    ledger_verified: bool = False
    environment: EnvironmentRecord | None = None

    @property
    def blocking_findings(self) -> list[EligibilityFinding]:
        return [f for f in self.findings if f.blocking]

    @model_validator(mode="after")
    def _check(self) -> BenchmarkReport:
        if self.verdict is QualificationVerdict.QUALIFYING_PASS:
            if self.exploratory:
                raise ValueError("an exploratory report cannot carry a qualifying pass")
            if any(f.blocking for f in self.findings):
                raise ValueError("a qualifying pass cannot be reported alongside blocking findings")
        return self
