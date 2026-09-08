"""Domain layer: validation, execution lifecycle, attempts and resource policy.

Nothing in this package imports a model runtime. Adapters are reached only
through :class:`animalite.adapters.registry.Registry`.
"""

from __future__ import annotations

from animalite.core.attempts import AttemptDirs, AttemptStore, new_attempt_id
from animalite.core.environment import capture_environment, git_state
from animalite.core.logging import AttemptLogger, StructuredLogger, utc_now
from animalite.core.resources import MemorySampler, thread_environment
from animalite.core.service import OUTPUT_FILENAME, LocalExecutionService
from animalite.core.validation import validate_request
from animalite.errors import (
    AdapterError,
    AnimaLiteError,
    AttemptConflictError,
    CodeVAL,
    EncoderError,
    JobTimeoutError,
    LedgerIntegrityError,
    OutputInvalidError,
    ProfileNotFoundError,
    ToolUnavailableError,
    ValidationRejected,
)

__all__ = [
    "OUTPUT_FILENAME",
    "AdapterError",
    "AnimaLiteError",
    "AttemptConflictError",
    "AttemptDirs",
    "AttemptLogger",
    "AttemptStore",
    "CodeVAL",
    "EncoderError",
    "JobTimeoutError",
    "LedgerIntegrityError",
    "LocalExecutionService",
    "MemorySampler",
    "OutputInvalidError",
    "ProfileNotFoundError",
    "StructuredLogger",
    "ToolUnavailableError",
    "ValidationRejected",
    "capture_environment",
    "git_state",
    "new_attempt_id",
    "thread_environment",
    "utc_now",
    "validate_request",
]
