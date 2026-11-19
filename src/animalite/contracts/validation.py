"""Validation report contract for ``validate()`` in the section 6.3 lifecycle.

Section 11 API rules: "Error responses must include a stable code, human
explanation and remediation hint". The same shape is used by the CLI, service
and benchmark so an unsupported control is reported, never raised as a crash.
"""

from __future__ import annotations

from pydantic import Field

from animalite.contracts.base import Document
from animalite.contracts.enums import IssueSeverity

__all__ = ["ValidationIssue", "ValidationReport"]


class ValidationIssue(Document):
    code: str = Field(min_length=1)
    severity: IssueSeverity = IssueSeverity.ERROR
    field_path: str = ""
    message: str
    remediation: str = ""


class ValidationReport(Document):
    valid: bool
    request_id: str | None = None
    profile_id: str | None = None
    issues: list[ValidationIssue] = Field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity is IssueSeverity.ERROR]

    @property
    def error_codes(self) -> list[str]:
        return [i.code for i in self.errors]

    def summary(self) -> str:
        if self.valid:
            warnings = len(self.issues) - len(self.errors)
            return f"valid ({warnings} non-blocking issue(s))"
        return "invalid: " + "; ".join(f"[{i.code}] {i.message}" for i in self.errors)
