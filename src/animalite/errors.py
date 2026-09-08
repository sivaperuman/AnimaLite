"""Exception hierarchy and stable validation issue codes.

This is a leaf module: it imports only from :mod:`animalite.contracts.enums`.
Keeping it out of :mod:`animalite.core` lets the adapter layer raise and
reference these types without importing the core package, which preserves the
one-directional dependency core -> adapters (handoff rule 1).
"""

from __future__ import annotations

from animalite.contracts.enums import FailureCategory

__all__ = [
    "AdapterError",
    "AnimaLiteError",
    "AttemptConflictError",
    "CodeVAL",
    "EncoderError",
    "JobTimeoutError",
    "LedgerIntegrityError",
    "OutputInvalidError",
    "ProfileNotFoundError",
    "ToolUnavailableError",
    "ValidationRejected",
]


class CodeVAL:
    """Stable validation issue codes.

    These strings appear in machine-readable CLI output and in run records, so
    they are part of the contract: add codes, do not rename them.
    """

    ANCHOR_COUNT = "VAL-ANCHOR-COUNT"
    ANCHOR_ORDER = "VAL-ANCHOR-ORDER"
    ANCHOR_ENDPOINTS = "VAL-ANCHOR-ENDPOINTS"
    ANCHOR_RANGE = "VAL-ANCHOR-RANGE"
    ANCHOR_GEOMETRY = "VAL-ANCHOR-GEOMETRY"
    ANCHOR_ASPECT = "VAL-ANCHOR-ASPECT"
    ANCHOR_MISSING_FILE = "VAL-ANCHOR-MISSING-FILE"
    ANCHOR_HASH_MISMATCH = "VAL-ANCHOR-HASH-MISMATCH"
    ANCHOR_NOT_APPROVED = "VAL-ANCHOR-NOT-APPROVED"
    PROFILE_UNKNOWN = "VAL-PROFILE-UNKNOWN"
    PROFILE_TIER = "VAL-PROFILE-TIER"
    PROFILE_RESOLUTION = "VAL-PROFILE-RESOLUTION"
    PROFILE_FRAME_COUNT = "VAL-PROFILE-FRAME-COUNT"
    PROFILE_ANCHOR_LIMIT = "VAL-PROFILE-ANCHOR-LIMIT"
    PROFILE_ENDPOINT_MODE = "VAL-PROFILE-ENDPOINT-MODE"
    PROFILE_ARTIFACT_UNVERIFIED = "VAL-PROFILE-ARTIFACT-UNVERIFIED"
    CONTROL_UNSUPPORTED = "VAL-CONTROL-UNSUPPORTED"
    CONTROL_VALUE_INVALID = "VAL-CONTROL-VALUE-INVALID"
    CADENCE_UNSUPPORTED = "VAL-CADENCE-UNSUPPORTED"
    DURATION_MISMATCH = "VAL-DURATION-MISMATCH"
    TOOL_UNAVAILABLE = "VAL-TOOL-UNAVAILABLE"
    NON_QUALIFYING_PROFILE = "VAL-NON-QUALIFYING-PROFILE"


class AnimaLiteError(Exception):
    """Base class. Every subclass maps to exactly one failure category."""

    category = FailureCategory.INTERNAL_ERROR


class ValidationRejected(AnimaLiteError):
    """Raised when execution is attempted on a request that failed validation."""

    category = FailureCategory.VALIDATION_REJECTED

    def __init__(self, message: str, codes: list[str] | None = None) -> None:
        super().__init__(message)
        self.codes = codes or []


class ProfileNotFoundError(AnimaLiteError):
    category = FailureCategory.VALIDATION_REJECTED


class AdapterError(AnimaLiteError):
    category = FailureCategory.ADAPTER_ERROR


class JobCancelled(AnimaLiteError):
    """Cancellation reached a blocking native operation and stopped it.

    Distinct from a timeout: the deadline had not expired. Kept separate so an
    attempt cancelled mid-encode is recorded as ``cancelled`` rather than being
    reported as an encoder fault or a deadline breach.
    """

    category = FailureCategory.CANCELLED


class EncoderError(AnimaLiteError):
    category = FailureCategory.ENCODER_ERROR


class JobTimeoutError(AnimaLiteError):
    """The job deadline elapsed. The process tree has already been torn down."""

    category = FailureCategory.TIMEOUT


class OutputInvalidError(AnimaLiteError):
    category = FailureCategory.OUTPUT_INVALID


class ToolUnavailableError(AnimaLiteError):
    category = FailureCategory.TOOL_UNAVAILABLE


class AttemptConflictError(AnimaLiteError):
    """Raised when a write would overwrite an existing attempt or output."""

    category = FailureCategory.INTERNAL_ERROR


class LedgerIntegrityError(AnimaLiteError):
    """Raised when a benchmark ledger has been truncated, reordered or rewritten."""

    category = FailureCategory.INTERNAL_ERROR
