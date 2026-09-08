"""Validation: invalid anchor count/order/timing and unsupported settings."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from animalite.adapters.registry import default_registry
from animalite.contracts.assets import AnchorSet
from animalite.contracts.enums import CadenceConversion, IssueSeverity, MotionTier
from animalite.contracts.media import P_L_FINAL_OUTPUT, CadencePolicy, OutputSpec
from animalite.core.validation import validate_request
from animalite.errors import CodeVAL
from animalite.media.ffmpeg import FFmpegTools
from tests.conftest import make_request, synthetic_anchor

TOOLS = FFmpegTools.discover()


def _report(anchors, **kwargs):
    request = make_request(anchors, **kwargs)
    return validate_request(request, default_registry(), tools=TOOLS)


def _endpoints(tmp_path, last=71):
    return [
        synthetic_anchor(tmp_path, animation_index=0, anchor_id="s"),
        synthetic_anchor(tmp_path, animation_index=last, anchor_id="e"),
    ]


# --- structural rules rejected at construction -------------------------------


def test_a_single_anchor_is_rejected(tmp_path):
    with pytest.raises(ValidationError, match="at least 2 items"):
        AnchorSet(anchors=[synthetic_anchor(tmp_path, animation_index=0)])


def test_five_anchors_are_rejected(tmp_path):
    anchors = [
        synthetic_anchor(tmp_path, animation_index=i, anchor_id=f"a{i}")
        for i in (0, 18, 36, 54, 71)
    ]
    with pytest.raises(ValidationError, match="at most 4 items"):
        AnchorSet(anchors=anchors)


def test_descending_anchor_order_is_rejected(tmp_path):
    anchors = [
        synthetic_anchor(tmp_path, animation_index=71, anchor_id="e"),
        synthetic_anchor(tmp_path, animation_index=0, anchor_id="s"),
    ]
    with pytest.raises(ValidationError, match="must ascend"):
        AnchorSet(anchors=anchors)


def test_duplicate_anchor_indices_are_rejected(tmp_path):
    anchors = [
        synthetic_anchor(tmp_path, animation_index=0, anchor_id="a"),
        synthetic_anchor(tmp_path, animation_index=0, anchor_id="b"),
    ]
    with pytest.raises(ValidationError, match="must be unique"):
        AnchorSet(anchors=anchors)


def test_mixed_anchor_geometry_is_rejected(tmp_path):
    anchors = [
        synthetic_anchor(tmp_path, animation_index=0, anchor_id="s"),
        synthetic_anchor(tmp_path, animation_index=71, anchor_id="e", width=320, height=180),
    ]
    with pytest.raises(ValidationError, match="must share one pixel geometry"):
        AnchorSet(anchors=anchors)


def test_unknown_contract_fields_are_not_silently_ignored():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        OutputSpec.model_validate(
            {"width": 640, "height": 360, "animation_frame_count": 72, "bitrate_kbps": 4000}
        )


# --- rules reported as actionable validation issues --------------------------


def test_endpoints_must_sit_at_animation_index_0_and_71(tmp_path):
    anchors = AnchorSet(anchors=_endpoints(tmp_path, last=70))
    report = _report(anchors)
    assert not report.valid
    assert CodeVAL.ANCHOR_ENDPOINTS in report.error_codes
    issue = next(i for i in report.errors if i.code == CodeVAL.ANCHOR_ENDPOINTS)
    assert "0 and 71" in issue.message
    assert issue.remediation


def test_an_unapproved_anchor_is_rejected(tmp_path):
    anchors = AnchorSet(
        anchors=[
            synthetic_anchor(tmp_path, animation_index=0, anchor_id="s", approved=False),
            synthetic_anchor(tmp_path, animation_index=71, anchor_id="e"),
        ]
    )
    report = _report(anchors)
    assert CodeVAL.ANCHOR_NOT_APPROVED in report.error_codes


def test_a_changed_input_file_fails_the_hash_check(tmp_path):
    anchors = AnchorSet(anchors=_endpoints(tmp_path))
    from pathlib import Path

    Path(anchors.anchors[0].asset.path).write_bytes(b"tampered")
    report = _report(anchors)
    assert CodeVAL.ANCHOR_HASH_MISMATCH in report.error_codes


def test_a_missing_input_file_is_reported(tmp_path):
    anchors = AnchorSet(anchors=_endpoints(tmp_path))
    from pathlib import Path

    Path(anchors.anchors[1].asset.path).unlink()
    report = _report(anchors)
    assert CodeVAL.ANCHOR_MISSING_FILE in report.error_codes


def test_wrong_aspect_ratio_is_rejected(tmp_path):
    anchors = AnchorSet(
        anchors=[
            synthetic_anchor(tmp_path, animation_index=0, anchor_id="s", width=640, height=480),
            synthetic_anchor(tmp_path, animation_index=71, anchor_id="e", width=640, height=480),
        ]
    )
    report = _report(anchors)
    assert CodeVAL.ANCHOR_ASPECT in report.error_codes


def test_unsupported_resolution_is_rejected(tmp_path):
    anchors = AnchorSet(anchors=_endpoints(tmp_path))
    hd = P_L_FINAL_OUTPUT.model_copy(update={"width": 1280, "height": 720})
    report = _report(anchors, output=hd)
    assert CodeVAL.PROFILE_RESOLUTION in report.error_codes


def test_unsupported_tier_is_rejected(tmp_path):
    from animalite.contracts.shot import ShotIntent

    anchors = AnchorSet(anchors=_endpoints(tmp_path))
    request = make_request(anchors)
    request = request.model_copy(
        update={
            "shot": ShotIntent(
                shot_code="T", target_duration_seconds=6.0, assigned_tier=MotionTier.E4
            )
        }
    )
    report = validate_request(request, default_registry(), tools=TOOLS)
    assert CodeVAL.PROFILE_TIER in report.error_codes


def test_unsupported_control_is_reported_not_ignored(tmp_path):
    anchors = AnchorSet(anchors=_endpoints(tmp_path))
    report = _report(anchors, controls={"optical_flow_strength": 0.8})
    assert CodeVAL.CONTROL_UNSUPPORTED in report.error_codes
    issue = next(i for i in report.errors if i.code == CodeVAL.CONTROL_UNSUPPORTED)
    assert "optical_flow_strength" in issue.message
    assert "ease" in issue.remediation


def test_a_supported_control_with_an_unsupported_value_is_rejected(tmp_path):
    anchors = AnchorSet(anchors=_endpoints(tmp_path))
    report = _report(anchors, controls={"ease": "bounce"})
    assert CodeVAL.CONTROL_UNSUPPORTED in report.error_codes


def test_interpolated_cadence_uplift_is_not_implemented(tmp_path):
    anchors = AnchorSet(anchors=_endpoints(tmp_path))
    output = P_L_FINAL_OUTPUT.model_copy(
        update={
            "cadence": CadencePolicy(
                animation_fps=12, delivery_fps=24, conversion=CadenceConversion.INTERPOLATE
            )
        }
    )
    request = make_request(anchors).model_copy(update={"output": output})
    report = validate_request(request, default_registry(), tools=TOOLS)
    assert CodeVAL.CADENCE_UNSUPPORTED in report.error_codes


def test_declared_duration_must_match_the_encoded_contract(tmp_path):
    from animalite.contracts.shot import ShotIntent

    anchors = AnchorSet(anchors=_endpoints(tmp_path))
    request = make_request(anchors).model_copy(
        update={"shot": ShotIntent(shot_code="T", target_duration_seconds=8.0)}
    )
    report = validate_request(request, default_registry(), tools=TOOLS)
    assert CodeVAL.DURATION_MISMATCH in report.error_codes


def test_unknown_profile_is_reported_with_the_registered_ids(tmp_path):
    anchors = AnchorSet(anchors=_endpoints(tmp_path))
    report = _report(anchors, profile_id="rife-ncnn-not-implemented")
    assert report.error_codes == [CodeVAL.PROFILE_UNKNOWN]
    assert "fixture-synthetic" in report.errors[0].message


def test_a_valid_fixture_request_still_warns_that_it_cannot_qualify(tmp_path):
    anchors = AnchorSet(anchors=_endpoints(tmp_path))
    report = _report(anchors)
    assert report.valid
    warnings = [i for i in report.issues if i.severity is IssueSeverity.WARNING]
    assert any(i.code == CodeVAL.NON_QUALIFYING_PROFILE for i in warnings)
