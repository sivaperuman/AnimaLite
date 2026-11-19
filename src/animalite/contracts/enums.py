"""Stable enumerations for states, categories and evidence status.

Handoff v0.2 section 4.2 requires named units and enums for states and errors.
The string values are part of the on-disk contract; renaming one is a schema
change, not a refactor.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "CadenceConversion",
    "EndpointControlMode",
    "EngineClass",
    "EvidenceStatus",
    "FailureCategory",
    "IssueSeverity",
    "JobState",
    "MemoryMethod",
    "MotionTier",
    "QualificationVerdict",
    "RunKind",
    "RunOutcome",
    "Stage",
]


class JobState(StrEnum):
    """Section 6.3 lifecycle states. Terminal states never transition again."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL_STATES


_TERMINAL_STATES = frozenset({JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED})


class FailureCategory(StrEnum):
    """Why an attempt did not publish output. Recorded in structured logs."""

    VALIDATION_REJECTED = "validation_rejected"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    ADAPTER_ERROR = "adapter_error"
    ENCODER_ERROR = "encoder_error"
    OUTPUT_INVALID = "output_invalid"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    CLEANUP_FAILED = "cleanup_failed"
    TOOL_UNAVAILABLE = "tool_unavailable"
    INTERNAL_ERROR = "internal_error"


class EngineClass(StrEnum):
    """MR-016 engine class declaration."""

    DETERMINISTIC = "deterministic"
    ML_ASSISTED = "ml_assisted"
    GENERATIVE = "generative"


class MotionTier(StrEnum):
    """Section 6.4 motion tiers."""

    E0 = "E0"
    E1 = "E1"
    E2 = "E2"
    E3 = "E3"
    E4 = "E4"


class CadenceConversion(StrEnum):
    """CR-004 conversion from animation cadence to delivery frame rate."""

    DUPLICATE = "duplicate"
    INTERPOLATE = "interpolate"


class EndpointControlMode(StrEnum):
    """Section 15.2 endpoint contract modes."""

    EXACT_ASSET = "exact_asset"
    DETERMINISTIC_STATE = "deterministic_state"
    BOUNDED_SIMILARITY = "bounded_similarity"


class IssueSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Stage(StrEnum):
    """Timed stages inside the section 12.0 warm measurement boundary.

    Every stage listed here is *inside* the boundary except
    :attr:`RUNTIME_RESIDENCY`, which is the only cost section 12.0 allows to
    carry over between warm runs.
    """

    VALIDATE = "validate"
    RESOLVE_INPUTS = "resolve_inputs"
    DECODE_ANCHORS = "decode_anchors"
    PREPARE_FEATURES = "prepare_features"
    TEMPORAL_SYNTHESIS = "temporal_synthesis"
    COMPOSITE_NORMALIZE = "composite_normalize"
    ENCODE = "encode"
    VALIDATE_OUTPUT = "validate_output"
    PUBLISH = "publish"
    RUNTIME_RESIDENCY = "runtime_residency"


class EvidenceStatus(StrEnum):
    """Distinguishes a measured observation from an absent one.

    ``UNAVAILABLE``/``PENDING``/``NOT_APPLICABLE`` must never be rendered as a
    zero measurement (handoff section 13, working code item 2).
    """

    MEASURED = "measured"
    UNAVAILABLE = "unavailable"
    PENDING = "pending"
    NOT_APPLICABLE = "not_applicable"


class MemoryMethod(StrEnum):
    """How a peak-memory observation was obtained, with its known scope."""

    CGROUP_V2_MEMORY_PEAK = "cgroup_v2_memory_peak"
    PROC_VMHWM_PLUS_CHILD_MAXRSS = "proc_vmhwm_plus_child_maxrss"
    NONE = "none"


class RunKind(StrEnum):
    """Section 12.0 timing boundaries. Each is measured and reported separately."""

    WARM_FINAL = "warm_final"
    COLD_FINAL = "cold_final"
    WARM_PREVIEW = "warm_preview"
    CONTINUOUS_WORKLOAD = "continuous_workload"


class RunOutcome(StrEnum):
    """Outcome of one planned benchmark run.

    ``NOT_RUN`` is a first-class ledger value: a planned observation that never
    produced a record is a missing observation, which blocks qualification. It
    is never silently dropped from the denominator.
    """

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMEOUT = "timeout"
    INVALID_OUTPUT = "invalid_output"
    NOT_RUN = "not_run"

    @property
    def is_valid_observation(self) -> bool:
        return self is RunOutcome.SUCCEEDED


class QualificationVerdict(StrEnum):
    """Verdict returned by the benchmark evaluator.

    Only :attr:`QUALIFYING_PASS` may ever be reported as a section 12.0 pass,
    and the evaluator refuses to emit it unless every eligibility precondition
    and every required observation is present.
    """

    QUALIFYING_PASS = "qualifying_pass"  # noqa: S105 - a verdict name, not a secret
    QUALIFYING_FAIL = "qualifying_fail"
    NOT_ELIGIBLE = "not_eligible"
