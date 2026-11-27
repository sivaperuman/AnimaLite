"""Execution admission: absence is not permission, and neither is a digest.

The property under test is narrow and load-bearing: a learned profile is not
executable without a recorded, approved decision covering its exact artifacts
and the run's purpose. Everything here is about the ways that could quietly
become false -- an empty directory reading as "fine", an unreadable record
being skipped, an approval widening to cover an artifact it never named.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from animalite.adapters.classical_warp import CLASSICAL_WARP_PROFILE
from animalite.adapters.rife_ncnn import RIFE_PROFILE
from animalite.admission import (
    AdmissionStore,
    evaluate_admission,
    profile_artifact_digests,
)
from animalite.contracts.admission import (
    AdmissionDecision,
    AdmissionPurpose,
    ExecutionAdmission,
)
from tests.conftest import write_admission

DIGESTS = profile_artifact_digests(RIFE_PROFILE)


def _store(tmp_path):
    return AdmissionStore(directory=tmp_path / "admissions")


def test_an_empty_directory_blocks_rather_than_permits(tmp_path):
    outcome = evaluate_admission(RIFE_PROFILE, AdmissionPurpose.RESEARCH, _store(tmp_path))
    assert not outcome.admitted
    assert outcome.state == "missing"
    assert "absence is not permission" in outcome.summary


def test_a_complete_approval_admits(tmp_path):
    write_admission(
        tmp_path / "admissions", profile_id=RIFE_PROFILE.profile_id, artifact_hashes=DIGESTS
    )
    outcome = evaluate_admission(RIFE_PROFILE, AdmissionPurpose.RESEARCH, _store(tmp_path))
    assert outcome.admitted
    assert outcome.state == "admitted"
    assert outcome.record is not None


@pytest.mark.parametrize("decision", [AdmissionDecision.PENDING, AdmissionDecision.REJECTED])
def test_pending_and_rejected_both_block(tmp_path, decision):
    write_admission(
        tmp_path / "admissions",
        profile_id=RIFE_PROFILE.profile_id,
        artifact_hashes=DIGESTS,
        decision=decision,
    )
    outcome = evaluate_admission(RIFE_PROFILE, AdmissionPurpose.RESEARCH, _store(tmp_path))
    assert not outcome.admitted
    assert outcome.state == decision.value


def test_an_approval_does_not_cover_an_artifact_it_never_named(tmp_path):
    """Adding a weight file must invalidate the old approval, not inherit it."""
    write_admission(
        tmp_path / "admissions",
        profile_id=RIFE_PROFILE.profile_id,
        artifact_hashes=DIGESTS[:-1],
    )
    outcome = evaluate_admission(RIFE_PROFILE, AdmissionPurpose.RESEARCH, _store(tmp_path))
    assert not outcome.admitted
    assert outcome.state == "artifacts_not_covered"
    assert outcome.uncovered_digests == (DIGESTS[-1],)


def test_an_approval_covers_only_the_purposes_it_lists(tmp_path):
    write_admission(
        tmp_path / "admissions",
        profile_id=RIFE_PROFILE.profile_id,
        artifact_hashes=DIGESTS,
        purposes=[AdmissionPurpose.RESEARCH],
    )
    store = _store(tmp_path)
    assert evaluate_admission(RIFE_PROFILE, AdmissionPurpose.RESEARCH, store).admitted
    for purpose in (
        AdmissionPurpose.BENCHMARK,
        AdmissionPurpose.PRODUCTION,
        AdmissionPurpose.REDISTRIBUTION,
    ):
        outcome = evaluate_admission(RIFE_PROFILE, purpose, store)
        assert not outcome.admitted, f"{purpose.value} was admitted by a research-only record"
        assert outcome.state == "purpose_not_permitted"


def test_a_record_for_another_profile_does_not_admit_this_one(tmp_path):
    write_admission(
        tmp_path / "admissions",
        profile_id="some-other-profile",
        artifact_hashes=DIGESTS,
    )
    outcome = evaluate_admission(RIFE_PROFILE, AdmissionPurpose.RESEARCH, _store(tmp_path))
    assert not outcome.admitted
    assert outcome.state == "missing"


def test_an_unreadable_record_blocks_instead_of_being_skipped(tmp_path):
    """A typo in an approval must not read as "no approval was recorded".

    Skipping it would be worse than blocking on it: a malformed *approval* would
    silently become an absent one, and an absent one blocks anyway -- but a
    malformed *rejection* would silently disappear.
    """
    directory = tmp_path / "admissions"
    directory.mkdir(parents=True)
    (directory / "broken.json").write_text("{not json", encoding="utf-8")
    outcome = evaluate_admission(RIFE_PROFILE, AdmissionPurpose.RESEARCH, _store(tmp_path))
    assert not outcome.admitted
    assert outcome.state == "unreadable"


def test_a_rejection_alongside_an_approval_does_not_silently_win_or_lose(tmp_path):
    """Two records: the approval decides, and the rejection is not lost.

    Recorded because the resolution order is a real decision. An operator who
    records a rejection and later records an approval has changed their mind;
    the newer approval governs, and `animalite runtime status` still lists both.
    """
    directory = tmp_path / "admissions"
    write_admission(
        directory,
        profile_id=RIFE_PROFILE.profile_id,
        artifact_hashes=DIGESTS,
        decision=AdmissionDecision.REJECTED,
        record_id="old-rejection",
    )
    write_admission(
        directory,
        profile_id=RIFE_PROFILE.profile_id,
        artifact_hashes=DIGESTS,
        record_id="new-approval",
    )
    store = _store(tmp_path)
    outcome = evaluate_admission(RIFE_PROFILE, AdmissionPurpose.RESEARCH, store)
    assert outcome.admitted
    assert {r.record_id for r in store.for_profile(RIFE_PROFILE.profile_id)} == {
        "old-rejection",
        "new-approval",
    }


def test_a_non_learned_profile_needs_no_admission():
    outcome = evaluate_admission(CLASSICAL_WARP_PROFILE, AdmissionPurpose.PRODUCTION)
    assert outcome.admitted
    assert outcome.state == "not_required"


# --- the contract refuses an approval that says nothing ----------------------


@pytest.mark.parametrize(
    "missing",
    ["reviewer", "reference", "recorded_at", "permitted_purposes", "artifact_hashes"],
)
def test_an_approval_missing_its_provenance_is_not_a_valid_record(missing):
    """An approval with these blank is the shape a bypass would take."""
    payload: dict[str, object] = {
        "record_id": "r1",
        "profile_id": RIFE_PROFILE.profile_id,
        "subject": "test",
        "decision": "approved",
        "artifact_hashes": DIGESTS,
        "permitted_purposes": ["research"],
        "reviewer": "someone",
        "reference": "doc",
        "recorded_at": "2026-01-01",
    }
    payload[missing] = [] if missing in ("permitted_purposes", "artifact_hashes") else None
    with pytest.raises(ValidationError, match=missing):
        ExecutionAdmission.model_validate(payload)


def test_a_pending_record_may_leave_provenance_blank():
    """The dossier is written before anyone has decided anything."""
    record = ExecutionAdmission(
        record_id="r1",
        profile_id=RIFE_PROFILE.profile_id,
        subject="test",
        decision=AdmissionDecision.PENDING,
    )
    assert record.decision is AdmissionDecision.PENDING
    assert record.permitted_purposes == []


def test_there_is_no_bypass_decision_value():
    """A "development" or "waived" state is the thing this contract prevents."""
    assert {d.value for d in AdmissionDecision} == {"approved", "pending", "rejected"}
