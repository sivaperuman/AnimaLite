"""Render request, job and attempt records for the section 6.3 lifecycle."""

from __future__ import annotations

from pydantic import Field, model_validator

from animalite.contracts.assets import AnchorSet
from animalite.contracts.base import Contract, Document, content_digest
from animalite.contracts.enums import FailureCategory, JobState
from animalite.contracts.media import FrameAccounting, OutputSpec
from animalite.contracts.profile import EngineProfile
from animalite.contracts.results import (
    DeviceEvidence,
    MemoryObservation,
    OutputManifest,
    StageTiming,
)
from animalite.contracts.shot import ShotIntent

__all__ = [
    "AttemptRecord",
    "CancelResult",
    "EnvironmentRecord",
    "ExecutionEnvelope",
    "FailureRecord",
    "JobStatus",
    "ProcessInstance",
    "RenderRequest",
]


class RenderRequest(Document):
    """One render request. Everything that affects the output is in here."""

    request_id: str = Field(min_length=1)
    shot: ShotIntent
    anchors: AnchorSet
    engine_profile_id: str = Field(min_length=1)
    output: OutputSpec
    controls: dict[str, float | int | str | bool] = Field(default_factory=dict)
    timeout_seconds: float = Field(
        default=600.0,
        gt=0.0,
        le=86_400.0,
        description=(
            "Finite job deadline. Enforced once per delivery frame and at the "
            "encoder wait, so the granularity is one frame rather than "
            "instantaneous. An adapter that blocks inside a single frame is not "
            "interrupted; that needs an out-of-process worker."
        ),
    )
    parent_attempt_id: str | None = None
    label: str | None = None

    def settings_digest(self) -> str:
        """Digest over the output-affecting subset of the request.

        Excludes ``request_id``, ``label``, ``timeout_seconds`` and
        ``parent_attempt_id``: those change bookkeeping, not pixels.
        """
        payload = {
            "shot": self.shot.to_json_obj(),
            "anchors": self.anchors.to_json_obj(),
            "engine_profile_id": self.engine_profile_id,
            "output": self.output.to_json_obj(),
            "controls": dict(sorted(self.controls.items())),
        }
        return content_digest(payload)


class EnvironmentRecord(Document):
    """Reproducibility inputs pinned per attempt (handoff rule 8)."""

    animalite_version: str
    schema_version: str
    code_commit: str | None = None
    code_tree_dirty: bool | None = None
    python_version: str
    platform: str
    architecture: str
    thread_environment: dict[str, str] = Field(default_factory=dict)
    tool_identities: dict[str, str] = Field(default_factory=dict)
    dependency_lock_digest: str | None = None
    cpu_flags_recorded: list[str] = Field(default_factory=list)


class FailureRecord(Contract):
    """Why an attempt failed, with a path to retained diagnostics."""

    category: FailureCategory
    message: str
    detail: str | None = None
    diagnostics_path: str | None = None
    child_exit_code: int | None = None
    validation_codes: list[str] = Field(default_factory=list)


class AttemptRecord(Document):
    """Immutable record of one execution attempt.

    A retry never mutates this record: it creates a new attempt whose
    ``parent_attempt_id`` points back here (handoff rule 4).
    """

    attempt_id: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    request: RenderRequest
    profile: EngineProfile
    settings_digest: str

    state: JobState = JobState.QUEUED
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None

    attempt_dir: str
    parent_attempt_id: str | None = None
    retry_index: int = Field(default=0, ge=0)

    stages: list[StageTiming] = Field(default_factory=list)
    frame_accounting: FrameAccounting | None = None
    output: OutputManifest | None = None
    memory: MemoryObservation = MemoryObservation.unavailable("not sampled")
    device_evidence: DeviceEvidence = DeviceEvidence()
    environment: EnvironmentRecord | None = None
    failure: FailureRecord | None = None
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    #: Process-group ids still alive after this attempt tore its children down.
    #: Non-empty means the cleanup guarantee did not hold, so it is recorded
    #: rather than discarded when the process context manager exits.
    cleanup_survivor_groups: list[int] = Field(default_factory=list)
    #: Free-form execution observations, including cleanup and runtime notes.
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_state_consistency(self) -> AttemptRecord:
        if self.state is JobState.SUCCEEDED:
            if self.output is None:
                raise ValueError("a succeeded attempt must carry an output manifest")
            if self.failure is not None:
                raise ValueError("a succeeded attempt must not carry a failure record")
        if self.state in (JobState.FAILED, JobState.CANCELLED):
            if self.failure is None:
                raise ValueError(f"a {self.state.value} attempt must carry a failure record")
            if self.output is not None:
                raise ValueError(
                    f"a {self.state.value} attempt must not publish an output manifest; "
                    "a partial file is not a successful result"
                )
        return self

    @property
    def wall_seconds(self) -> float | None:
        """Total in-boundary wall time, or ``None`` when nothing was timed."""
        timed = [s.wall_seconds for s in self.stages if s.inside_timing_boundary]
        return sum(timed) if timed else None


class ProcessInstance(Contract):
    """Identity of one operating-system process *instance*.

    A pid alone does not identify a process: pids are reused. ``(boot_id, pid,
    start_ticks)`` does, because start time distinguishes a recycled pid from
    the original. That is what makes "this really was a new process" checkable
    rather than asserted -- two process-cold runs must not share an instance
    key.
    """

    pid: int = Field(ge=0)
    boot_id: str | None = None
    start_ticks: int | None = Field(default=None, ge=0)
    interpreter: str | None = None

    @property
    def instance_key(self) -> str:
        """Stable identity string; two distinct process instances never match."""
        return f"{self.boot_id or 'unknown-boot'}:{self.pid}:{self.start_ticks}"

    @property
    def is_identified(self) -> bool:
        """True when the key rests on measured start time, not on the pid alone."""
        return self.boot_id is not None and self.start_ticks is not None


class ExecutionEnvelope(Document):
    """A complete, self-contained job handed to a separate interpreter.

    Passing only ``engine_profile_id`` across the process boundary let the child
    rebuild the *default* registry and silently execute a different resolved
    profile: with an overridden ``fixture-synthetic`` registered in the parent,
    the warm and cold runs of one plan produced different outputs while both
    recorded success under the same planned profile.

    So the resolved profile travels with the request and is re-derived and
    re-checked on arrival. This is data, never code: no pickled registry, no
    importable module path, and the child resolves the adapter only from its own
    built-in allowlist by ``adapter_key``.
    """

    envelope_id: str = Field(min_length=1)
    request: RenderRequest
    profile: EngineProfile
    #: ``content_digest(profile)`` computed by the sender. The receiver
    #: recomputes it and refuses to execute on a mismatch.
    profile_digest: str = Field(min_length=1)
    #: Written by the child at startup, before any work, so the launcher can
    #: tell "never started" from "started and failed".
    process_marker_path: str | None = None

    @model_validator(mode="after")
    def _check_profile_matches_request(self) -> ExecutionEnvelope:
        if self.profile.profile_id != self.request.engine_profile_id:
            raise ValueError(
                f"envelope profile {self.profile.profile_id!r} does not match the "
                f"request's engine_profile_id {self.request.engine_profile_id!r}"
            )
        return self


class JobStatus(Document):
    """Result of ``status(job_id)``."""

    job_id: str
    attempt_id: str
    state: JobState
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    stage: str | None = None
    failure: FailureRecord | None = None
    output_path: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class CancelResult(Document):
    """Result of ``cancel(job_id)``. Reports unsupported safe cancellation honestly."""

    job_id: str
    accepted: bool
    state: JobState
    safe_cancellation_supported: bool
    message: str
