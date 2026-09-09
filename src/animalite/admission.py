"""Enforcement of execution admission for learned profiles (CR-024, C-04).

Leaf module: it imports only :mod:`animalite.contracts`, so validation, the
adapters and the CLI can all consult the same rule without any of them
importing each other.

The rule is one sentence: **a profile whose learned component participates in
temporal synthesis may not be executed unless an approved admission record
covers its exact artifacts and the run's purpose.** Missing, pending and
rejected all block, and they block before any native invocation rather than at
the qualification evaluator -- refusing to *count* a run that already downloaded
weights, launched the runtime and produced frames is not enforcement.

Records are read from a directory, one JSON file each::

    ANIMALITE_ADMISSION_DIR=/path/to/records   # explicit
    $XDG_DATA_HOME/animalite/admissions        # default

Deliberately not from the source tree: an approval is an operator's recorded
decision about their own use, and shipping one in the repository would make
every checkout inherit it. ``docs/licensing/admissions/`` holds the *dossier*
for the pending RIFE decision -- the artifact list and the purposes being
requested -- which is what a reviewer signs. It is a template, and it carries
``decision: pending``, so copying it into place installs a block, not a pass.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from animalite.contracts.admission import (
    AdmissionDecision,
    AdmissionPurpose,
    ExecutionAdmission,
)
from animalite.contracts.profile import EngineProfile

__all__ = [
    "AdmissionOutcome",
    "AdmissionStore",
    "admission_directory",
    "evaluate_admission",
    "profile_artifact_digests",
]


def admission_directory() -> Path:
    """Where recorded admission decisions are read from."""
    override = os.environ.get("ANIMALITE_ADMISSION_DIR")
    if override:
        return Path(override)
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "animalite" / "admissions"


def profile_artifact_digests(profile: EngineProfile) -> list[str]:
    """Every declared artifact digest the profile would execute or load."""
    return sorted(
        artifact.content_hash
        for artifact in (*profile.binaries, *profile.weights)
        if artifact.content_hash
    )


@dataclass(frozen=True)
class AdmissionOutcome:
    """Whether execution is admitted, and precisely why not when it is not.

    ``state`` is a stable short string so a CLI, a validation issue and a log
    line can all name the same condition: ``not_required``, ``missing``,
    ``pending``, ``rejected``, ``unreadable``, ``artifacts_not_covered``,
    ``purpose_not_permitted`` or ``admitted``.
    """

    admitted: bool
    state: str
    reasons: list[str] = field(default_factory=list)
    record: ExecutionAdmission | None = None
    #: Digests the run needs that the record does not cover. Empty when the
    #: record covers everything, *or* when there is no record at all -- read it
    #: together with ``state``.
    uncovered_digests: tuple[str, ...] = ()

    @property
    def summary(self) -> str:
        return f"{self.state}: {'; '.join(self.reasons)}" if self.reasons else self.state


@dataclass(frozen=True)
class AdmissionStore:
    """Recorded admission decisions, read from a directory of JSON files."""

    directory: Path

    @classmethod
    def default(cls) -> AdmissionStore:
        """The store configured by the environment.

        Resolved per call rather than cached: an operator recording a decision
        must not have to restart a long-lived process for it to take effect,
        and a test must not inherit another test's directory.
        """
        return cls(directory=admission_directory())

    def records(self) -> list[ExecutionAdmission]:
        """Every readable record in the directory, sorted by id."""
        found, _ = self._load()
        return sorted(found, key=lambda r: r.record_id)

    def problems(self) -> list[str]:
        """Files that exist but could not be read as admission records."""
        _, problems = self._load()
        return problems

    def for_profile(self, profile_id: str) -> list[ExecutionAdmission]:
        return [r for r in self.records() if r.profile_id == profile_id]

    def _load(self) -> tuple[list[ExecutionAdmission], list[str]]:
        records: list[ExecutionAdmission] = []
        problems: list[str] = []
        if not self.directory.is_dir():
            return records, problems
        for path in sorted(self.directory.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                records.append(ExecutionAdmission.model_validate(payload))
            except Exception as exc:
                # An unreadable record is reported, never skipped: a typo in an
                # approval must not read as "no approval was ever recorded",
                # and it must certainly not read as a pass.
                problems.append(f"{path.name}: {type(exc).__name__}: {exc}")
        return records, problems


def evaluate_admission(
    profile: EngineProfile,
    purpose: AdmissionPurpose,
    store: AdmissionStore | None = None,
) -> AdmissionOutcome:
    """Decide whether ``profile`` may be executed for ``purpose``.

    Non-learned profiles need no admission: the comparator and the fixture
    adapter execute nothing whose terms are in question. That exemption is
    keyed on ``learned_temporal_participation`` -- the same field MR-018 uses
    to decide what may qualify -- so a profile cannot be exempt from admission
    and eligible for qualification at the same time.
    """
    if not profile.learned_temporal_participation:
        return AdmissionOutcome(
            admitted=True,
            state="not_required",
            reasons=[
                f"profile {profile.profile_id!r} declares no learned temporal "
                "participation, so no third-party model artifacts are executed"
            ],
        )

    resolved = store if store is not None else AdmissionStore.default()
    needed = profile_artifact_digests(profile)
    candidates = resolved.for_profile(profile.profile_id)
    unreadable = resolved.problems()

    if unreadable:
        return AdmissionOutcome(
            admitted=False,
            state="unreadable",
            reasons=[
                f"admission record(s) in {resolved.directory} could not be read: "
                + "; ".join(unreadable),
                "an unreadable record is not an approval",
            ],
        )

    if not candidates:
        return AdmissionOutcome(
            admitted=False,
            state="missing",
            reasons=[
                f"no execution admission record for profile {profile.profile_id!r} "
                f"in {resolved.directory}",
                "absence is not permission: record the reviewed disposition "
                "before executing the pinned artifacts (CR-024, DEC-0013)",
            ],
            uncovered_digests=tuple(needed),
        )

    approved = [r for r in candidates if r.decision is AdmissionDecision.APPROVED]
    if not approved:
        blocking = candidates[0]
        return AdmissionOutcome(
            admitted=False,
            state=blocking.decision.value,
            reasons=[
                f"admission record {blocking.record_id!r} for "
                f"{profile.profile_id!r} is {blocking.decision.value!r}",
                *blocking.notes,
            ],
            record=blocking,
            uncovered_digests=tuple(needed),
        )

    # Report against the record that comes closest, so the message names the
    # one thing to fix rather than the first record on disk.
    ranked = sorted(
        approved,
        key=lambda r: (len(r.covers(needed)), 0 if r.permits(purpose) else 1),
    )
    for record in ranked:
        uncovered = record.covers(needed)
        if uncovered:
            continue
        if not record.permits(purpose):
            continue
        return AdmissionOutcome(
            admitted=True,
            state="admitted",
            reasons=[
                f"admission {record.record_id!r} approved by "
                f"{record.reviewer} on {record.recorded_at} permits "
                f"{purpose.value} for {len(record.artifact_hashes)} artifact(s)",
                *record.conditions,
            ],
            record=record,
        )

    best = ranked[0]
    uncovered = best.covers(needed)
    if uncovered:
        return AdmissionOutcome(
            admitted=False,
            state="artifacts_not_covered",
            reasons=[
                f"admission {best.record_id!r} does not cover "
                f"{len(uncovered)} artifact digest(s) this profile declares: "
                f"{', '.join(uncovered)}",
                "an approval covers the exact artifacts it names; changing or "
                "adding one requires a new decision",
            ],
            record=best,
            uncovered_digests=tuple(uncovered),
        )
    return AdmissionOutcome(
        admitted=False,
        state="purpose_not_permitted",
        reasons=[
            f"admission {best.record_id!r} permits "
            f"{[p.value for p in best.permitted_purposes]}, not {purpose.value!r}",
        ],
        record=best,
    )
