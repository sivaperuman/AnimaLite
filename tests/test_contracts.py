"""Contract behaviour: versioning, canonical hashing and evidence honesty."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from tests.conftest import make_request, synthetic_anchor

from animalite import SCHEMA_VERSION
from animalite.contracts.assets import AnchorSet
from animalite.contracts.base import canonical_json, content_digest, sha256_file
from animalite.contracts.enums import (
    EvidenceStatus,
    JobState,
    MemoryMethod,
    RunOutcome,
)
from animalite.contracts.estimate import ResourceEstimate, ReusableSetupUnit
from animalite.contracts.media import P_L_FINAL_OUTPUT, FrameAccounting
from animalite.contracts.profile import ThreadBudget
from animalite.contracts.results import DecodeProbe, MemoryObservation, OutputManifest


def test_documents_carry_the_schema_version():
    assert P_L_FINAL_OUTPUT.model_dump()  # value objects need no version
    request = make_request(
        AnchorSet(
            anchors=[
                synthetic_anchor(_tmp(), animation_index=0, anchor_id="s"),
                synthetic_anchor(_tmp(), animation_index=71, anchor_id="e"),
            ]
        )
    )
    assert request.schema_version == SCHEMA_VERSION
    assert request.to_json_obj()["schema_version"] == SCHEMA_VERSION


_TMP = None


def _tmp():
    global _TMP
    if _TMP is None:
        import tempfile
        from pathlib import Path

        _TMP = Path(tempfile.mkdtemp())
    return _TMP


def test_canonical_json_is_key_order_independent():
    a = {"b": 1, "a": {"z": 1, "y": 2}}
    b = {"a": {"y": 2, "z": 1}, "b": 1}
    assert canonical_json(a) == canonical_json(b)
    assert content_digest(a) == content_digest(b)
    assert canonical_json(a) == b'{"a":{"y":2,"z":1},"b":1}'


def test_canonical_json_rejects_non_finite_numbers():
    with pytest.raises(ValueError):
        canonical_json({"x": float("nan")})


def test_settings_digest_ignores_bookkeeping_but_tracks_output_settings():
    anchors = AnchorSet(
        anchors=[
            synthetic_anchor(_tmp(), animation_index=0, anchor_id="s"),
            synthetic_anchor(_tmp(), animation_index=71, anchor_id="e"),
        ]
    )
    base = make_request(anchors, request_id="one")
    renamed = make_request(anchors, request_id="two", timeout_seconds=999.0)
    assert base.settings_digest() == renamed.settings_digest()

    recoded = base.model_copy(update={"output": P_L_FINAL_OUTPUT.model_copy(update={"crf": 30})})
    assert recoded.settings_digest() != base.settings_digest()

    controlled = make_request(anchors, request_id="one", controls={"ease": "linear"})
    assert controlled.settings_digest() != base.settings_digest()


def test_sha256_file_matches_hashlib(tmp_path):
    import hashlib

    path = tmp_path / "f.bin"
    path.write_bytes(b"animalite" * 1000)
    assert sha256_file(str(path)) == "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def test_unavailable_evidence_is_never_zero():
    unavailable = MemoryObservation.unavailable("no counter on this platform")
    assert unavailable.status is EvidenceStatus.UNAVAILABLE
    assert unavailable.peak_bytes is None
    with pytest.raises(ValueError, match="not a zero measurement"):
        MemoryObservation(status=EvidenceStatus.PENDING, peak_bytes=0)
    with pytest.raises(ValueError, match="requires peak_bytes"):
        MemoryObservation(status=EvidenceStatus.MEASURED, method=MemoryMethod.CGROUP_V2_MEMORY_PEAK)
    with pytest.raises(ValueError, match="requires a memory method"):
        MemoryObservation(status=EvidenceStatus.MEASURED, peak_bytes=1)


def test_estimates_and_observations_are_distinct_types():
    estimate = ResourceEstimate(
        profile_id="p",
        preparation_active_seconds=0.0,
        preparation_wall_seconds=0.0,
        cold_start_seconds=1.0,
        preview_wall_seconds=0.0,
        render_encode_wall_seconds=2.0,
        input_anchor_count=2,
        animation_frame_count=72,
        delivery_frame_count=144,
        peak_application_memory_bytes=1,
        thread_count=4,
        scratch_storage_mb=1.0,
        reusable_setup_units=[
            ReusableSetupUnit(
                unit_kind="character_package",
                unit_count=1,
                artist_hours_per_unit=16.0,
                accelerator_minutes_per_unit=0.0,
            )
        ],
        basis="heuristic",
    )
    assert estimate.kind == "estimate"
    assert estimate.is_measured is False
    # CR-006: accelerator fields are optional, not required contract fields.
    assert estimate.accelerator_type is None
    assert estimate.accelerator_minutes is None


def test_thread_budget_cannot_be_over_allocated():
    with pytest.raises(ValidationError, match="over-allocated"):
        ThreadBudget(total_threads=4, python_threads=2, inference_threads=2, encoder_threads=2)
    ok = ThreadBudget(total_threads=4, python_threads=1, inference_threads=1, encoder_threads=2)
    assert ok.total_threads == 4


def test_output_manifest_must_explain_a_non_qualifying_label():
    probe = DecodeProbe(
        container_format="mp4",
        codec="h264",
        width=640,
        height=360,
        pixel_format="yuv420p",
        counted_frames=144,
        avg_frame_rate="24/1",
        duration_seconds=6.0,
        size_bytes=10,
    )
    counts = FrameAccounting(
        animation_frame_count=72,
        delivery_frame_count=144,
        source_frame_count=2,
        synthesized_frame_count=70,
        duplicated_frame_count=72,
    )
    with pytest.raises(ValidationError, match="non_qualifying_reason"):
        OutputManifest(
            path="/x.mp4",
            content_hash="sha256:" + "0" * 64,
            frame_accounting=counts,
            probe=probe,
            settings_digest="sha256:" + "1" * 64,
            is_qualifying_evidence=False,
        )


def test_a_succeeded_attempt_must_carry_output_and_a_failed_one_must_not():
    from animalite.contracts.enums import FailureCategory
    from animalite.contracts.job import AttemptRecord, FailureRecord

    anchors = AnchorSet(
        anchors=[
            synthetic_anchor(_tmp(), animation_index=0, anchor_id="s"),
            synthetic_anchor(_tmp(), animation_index=71, anchor_id="e"),
        ]
    )
    from animalite.adapters.fixture import FIXTURE_PROFILE

    common = {
        "attempt_id": "a",
        "job_id": "a",
        "request": make_request(anchors),
        "profile": FIXTURE_PROFILE,
        "settings_digest": "sha256:" + "0" * 64,
        "created_at": "2026-01-01T00:00:00.000000Z",
        "attempt_dir": str(_tmp() / "attempt"),
    }
    with pytest.raises(ValidationError, match="must carry an output manifest"):
        AttemptRecord(state=JobState.SUCCEEDED, **common)
    with pytest.raises(ValidationError, match="must carry a failure record"):
        AttemptRecord(state=JobState.FAILED, **common)
    ok = AttemptRecord(
        state=JobState.FAILED,
        failure=FailureRecord(category=FailureCategory.ADAPTER_ERROR, message="boom"),
        **common,
    )
    assert ok.output is None


def test_terminal_states_are_identified():
    assert JobState.SUCCEEDED.is_terminal
    assert JobState.FAILED.is_terminal
    assert JobState.CANCELLED.is_terminal
    assert not JobState.QUEUED.is_terminal
    assert not JobState.RUNNING.is_terminal


def test_only_a_succeeded_run_is_a_valid_observation():
    assert RunOutcome.SUCCEEDED.is_valid_observation
    for outcome in (
        RunOutcome.FAILED,
        RunOutcome.TIMEOUT,
        RunOutcome.INVALID_OUTPUT,
        RunOutcome.NOT_RUN,
    ):
        assert not outcome.is_valid_observation


def test_contracts_round_trip_through_json():
    payload = json.loads(json.dumps(P_L_FINAL_OUTPUT.to_json_obj()))
    from animalite.contracts.media import OutputSpec

    assert OutputSpec.model_validate(payload) == P_L_FINAL_OUTPUT
