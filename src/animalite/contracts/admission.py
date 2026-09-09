"""Execution admission: the recorded permission to run a learned candidate.

Artifact *verification* and execution *admission* are two different questions
and this module exists because Package B conflated them. Verification asks "are
these the bytes we pinned?" -- a hash answers it. Admission asks "are we
permitted to execute these artifacts, for this purpose?" -- only a recorded
human disposition answers that, and no digest, install or flag can stand in for
one (CR-024, C-04, DEC-0013).

An :class:`ExecutionAdmission` is therefore a *record of a decision someone
made*, not a computed property. It binds four things together so that an
approval cannot quietly widen:

* the profile it was granted for,
* the exact artifact digests it covers,
* the purposes it permits,
* who recorded it and where the reasoning lives.

Absence is not permission. A profile with no admission record is treated
exactly like one whose record is ``pending``: blocked.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from animalite.contracts.base import Document

__all__ = [
    "AdmissionDecision",
    "AdmissionPurpose",
    "ExecutionAdmission",
]


class AdmissionDecision(StrEnum):
    """State of a recorded admission decision.

    There is deliberately no ``waived`` or ``development`` member: a bypass
    state is the thing this contract exists to prevent.
    """

    APPROVED = "approved"
    PENDING = "pending"
    REJECTED = "rejected"


class AdmissionPurpose(StrEnum):
    """What a run is for. Admission is granted per purpose, never in general.

    Splitting these matters because the upstream terms differ by use: local
    research on synthetic frames, benchmark evidence, shipping output to a
    customer and redistributing the artifacts themselves are four different
    permissions, and a record that clears one clears only that one.
    """

    RESEARCH = "research"
    BENCHMARK = "benchmark"
    PRODUCTION = "production"
    REDISTRIBUTION = "redistribution"


class ExecutionAdmission(Document):
    """A recorded decision about executing one profile's pinned artifacts.

    Round-tripped as JSON so a reviewer's disposition lives in a file with a
    name, a date and a reference rather than in code. The validator refuses an
    ``approved`` record that does not say who approved it, what it covers and
    what it permits -- an approval with those fields blank is the shape a
    bypass would take.
    """

    record_id: str = Field(min_length=1)
    profile_id: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    decision: AdmissionDecision
    #: Digests (``sha256:...``) this decision covers. Every artifact the profile
    #: declares must appear here, so adding a weight file to a profile
    #: invalidates the old approval instead of inheriting it.
    artifact_hashes: list[str] = Field(default_factory=list)
    permitted_purposes: list[AdmissionPurpose] = Field(default_factory=list)
    reviewer: str | None = None
    #: Where the reasoning lives: a decision record, an issue, a signed note.
    reference: str | None = None
    recorded_at: str | None = None
    conditions: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_approval_is_complete(self) -> ExecutionAdmission:
        if self.decision is not AdmissionDecision.APPROVED:
            return self
        missing = [
            name
            for name, value in (
                ("reviewer", self.reviewer),
                ("reference", self.reference),
                ("recorded_at", self.recorded_at),
                ("permitted_purposes", self.permitted_purposes),
                ("artifact_hashes", self.artifact_hashes),
            )
            if not value
        ]
        if missing:
            raise ValueError(
                f"admission record {self.record_id!r} is 'approved' but does not "
                f"record {', '.join(missing)}; an approval must name the reviewer, "
                "the reference, the date, the permitted purposes and the exact "
                "artifacts it covers"
            )
        return self

    def covers(self, digests: list[str]) -> list[str]:
        """Digests from ``digests`` this record does **not** cover."""
        held = set(self.artifact_hashes)
        return [d for d in digests if d not in held]

    def permits(self, purpose: AdmissionPurpose) -> bool:
        return purpose in self.permitted_purposes
