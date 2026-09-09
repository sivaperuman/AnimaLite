"""The classical warp/flow comparator: it must work, and it must never qualify.

Ground truth is constructed rather than eyeballed. A known translation gives a
frame we can demand back, so "does motion compensation actually happen" is a
measurement instead of an impression.
"""

from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from animalite.adapters.base import AdapterContext
from animalite.adapters.classical_warp import (
    CLASSICAL_WARP_PROFILE,
    ClassicalWarpAdapter,
)
from animalite.adapters.registry import default_registry
from animalite.contracts.assets import AnchorSet
from animalite.contracts.media import P_L_FINAL_OUTPUT
from animalite.contracts.profile import EngineProfile
from animalite.core.validation import validate_request
from animalite.errors import AdapterError, CodeVAL
from animalite.media.ffmpeg import FFmpegTools
from animalite.media.flow import (
    estimate_block_flow,
    interpolate_motion_compensated,
    upsample_flow,
    warp_bilinear,
)
from tests.conftest import make_request, synthetic_anchor

TOOLS = FFmpegTools.discover()
SHIFT = 24


def _textured_pair(width: int = 640, height: int = 360, shift: int = SHIFT):
    """Two frames related by a known horizontal translation, plus the midpoint.

    Texture matters: block matching on a flat field has nothing to match, so a
    smooth gradient would test nothing. The 4x upscaling of random blocks gives
    matchable structure at the macroblock scale.
    """
    rng = np.random.default_rng(7)
    base = rng.integers(0, 256, size=(height, width + 64, 3), dtype=np.uint8)
    base = np.repeat(np.repeat(base[::4, ::4], 4, axis=0), 4, axis=1)[:height, : width + 64]
    first = np.ascontiguousarray(base[:, :width])
    middle = np.ascontiguousarray(base[:, shift // 2 : shift // 2 + width])
    second = np.ascontiguousarray(base[:, shift : shift + width])
    return first, middle, second


# --- the property that justifies having a comparator at all ------------------


def test_the_comparator_beats_a_cross_fade_on_real_motion():
    """A baseline that only blends would prove nothing about the learned model.

    The comparator has to actually compensate for motion, otherwise "the
    learned candidate beat the baseline" would just mean "it beat a cross-fade",
    which MR-018 already excludes as evidence.
    """
    first, middle, second = _textured_pair()
    forward = estimate_block_flow(first, second, search_radius=32)
    backward = estimate_block_flow(second, first, search_radius=32)
    compensated = interpolate_motion_compensated(first, second, 0.5, forward, backward)

    truth = middle.astype(np.float32)
    cross_fade = first.astype(np.float32) * 0.5 + second.astype(np.float32) * 0.5
    mc_error = float(np.abs(compensated.astype(np.float32) - truth).mean())
    xf_error = float(np.abs(cross_fade - truth).mean())

    assert mc_error < xf_error / 5.0, (
        f"motion compensation ({mc_error:.2f} MAE) is not decisively better than a "
        f"cross-fade ({xf_error:.2f} MAE); the warp may be applied with the wrong sign"
    )


def test_the_estimated_flow_matches_the_known_translation():
    """The search must recover the real displacement, not merely some improvement."""
    first, _middle, second = _textured_pair()
    flow = estimate_block_flow(first, second, search_radius=32)
    # flow[p] = d with first[p] ~ second[p + d]; a rightward shift of the window
    # means content is found at a negative offset.
    assert flow[..., 0].mean() == pytest.approx(-SHIFT, abs=2.0)
    assert abs(float(flow[..., 1].mean())) < 1.0, "no vertical motion was introduced"


def test_a_flat_field_reports_no_motion_rather_than_a_confident_guess():
    """Block matching locks onto noise unless standing still is the incumbent.

    Measured on the two-anchor fixture before this rule existed: a mean
    displacement of 15.3 px saturating the search radius, on content whose true
    motion is about 2 px.
    """
    flat = np.full((64, 64, 3), 128, dtype=np.uint8)
    other = np.full((64, 64, 3), 130, dtype=np.uint8)
    flow = estimate_block_flow(flat, other, search_radius=8)
    assert not np.any(flow), f"a featureless pair produced motion {flow[np.nonzero(flow)]}"


def test_motion_beyond_the_search_radius_is_not_invented():
    """Unfound motion must report zero, not the best wrong answer at the edge."""
    first, _middle, second = _textured_pair(shift=60)
    flow = estimate_block_flow(first, second, search_radius=8)
    assert np.abs(flow).max() <= 8, "the estimator exceeded its own search radius"


def test_the_anchor_timesteps_return_the_anchors_untouched():
    """An approved frame is delivered exactly, never round-tripped through a warp."""
    first, _middle, second = _textured_pair()
    forward = estimate_block_flow(first, second)
    backward = estimate_block_flow(second, first)
    assert np.array_equal(
        interpolate_motion_compensated(first, second, 0.0, forward, backward), first
    )
    assert np.array_equal(
        interpolate_motion_compensated(first, second, 1.0, forward, backward), second
    )


def test_warping_by_a_zero_field_is_the_identity():
    first, _middle, _second = _textured_pair(width=64, height=64)
    zero = np.zeros((64, 64, 2), dtype=np.float32)
    assert np.allclose(warp_bilinear(first, zero), first.astype(np.float32))


def test_upsampled_flow_keeps_the_block_values_at_block_centres():
    flow = np.zeros((4, 4, 2), dtype=np.float32)
    flow[2, 3] = (5.0, -3.0)
    dense = upsample_flow(flow, 64, 64, block_size=16)
    # Centre of block (2, 3) is pixel (2*16+8, 3*16+8) = (40, 56).
    assert dense[40, 56] == pytest.approx([5.0, -3.0], abs=1e-4)


# --- it must never be able to qualify ---------------------------------------


def test_the_comparator_profile_is_not_qualification_eligible():
    assert CLASSICAL_WARP_PROFILE.qualification_eligible is False
    assert CLASSICAL_WARP_PROFILE.learned_temporal_participation is False
    assert "MR-018" in (CLASSICAL_WARP_PROFILE.non_qualifying_reason or "")


def test_the_comparator_cannot_be_marked_eligible_even_by_editing_the_profile():
    """The contract refuses it, so this is not merely a declared intention.

    Validated from a dumped dict rather than `model_copy`, because `model_copy`
    does not re-run validators -- a test built on it would pass without the
    guard existing at all.
    """
    payload = CLASSICAL_WARP_PROFILE.model_dump()
    payload["qualification_eligible"] = True
    with pytest.raises(ValidationError, match="MR-018 requires the learned compon"):
        EngineProfile.model_validate(payload)


def test_capabilities_report_the_comparator_as_non_learned():
    caps = ClassicalWarpAdapter().capabilities(CLASSICAL_WARP_PROFILE)
    assert caps.learned_temporal_participation is False
    assert caps.qualification_eligible is False
    assert caps.cpu_only_guaranteed is True
    assert any("not evidence of learned capability" in note for note in caps.notes)


def test_validation_warns_that_the_comparator_is_a_baseline(tmp_path):
    anchors = AnchorSet(
        anchors=[
            synthetic_anchor(tmp_path, animation_index=0, anchor_id="s"),
            synthetic_anchor(tmp_path, animation_index=71, anchor_id="e"),
        ]
    )
    report = validate_request(
        make_request(anchors, profile_id="classical-warp-baseline"),
        default_registry(),
        tools=TOOLS,
    )
    assert CodeVAL.NON_QUALIFYING_PROFILE in {i.code for i in report.issues}


# --- control validation ------------------------------------------------------


@pytest.mark.parametrize(
    ("controls", "expected"),
    [
        ({"block_size": 7}, CodeVAL.CONTROL_VALUE_INVALID),
        ({"block_size": True}, CodeVAL.CONTROL_VALUE_INVALID),
        ({"search_radius": -1}, CodeVAL.CONTROL_VALUE_INVALID),
        ({"search_radius": 4096}, CodeVAL.CONTROL_VALUE_INVALID),
        ({"search_radius": float("nan")}, CodeVAL.CONTROL_VALUE_INVALID),
        ({"accept_margin": -0.5}, CodeVAL.CONTROL_VALUE_INVALID),
        ({"unknown_knob": 1}, CodeVAL.CONTROL_UNSUPPORTED),
    ],
)
def test_invalid_comparator_controls_are_rejected_before_execution(tmp_path, controls, expected):
    anchors = AnchorSet(
        anchors=[
            synthetic_anchor(tmp_path, animation_index=0, anchor_id="s"),
            synthetic_anchor(tmp_path, animation_index=71, anchor_id="e"),
        ]
    )
    report = validate_request(
        make_request(anchors, profile_id="classical-warp-baseline", controls=controls),
        default_registry(),
        tools=TOOLS,
    )
    assert not report.valid
    assert expected in report.error_codes


def test_a_bad_control_reaching_synthesis_directly_is_an_adapter_error(tmp_path):
    """Driven without the service, the adapter applies the same check."""
    first, _middle, second = _textured_pair(width=64, height=64)
    anchors = AnchorSet(
        anchors=[
            synthetic_anchor(tmp_path, animation_index=0, anchor_id="s"),
            synthetic_anchor(tmp_path, animation_index=71, anchor_id="e"),
        ]
    )
    context = AdapterContext(
        anchor_frames={0: first, 71: second},
        output=P_L_FINAL_OUTPUT.model_copy(update={"width": 64, "height": 64}),
        anchors=anchors,
        profile=CLASSICAL_WARP_PROFILE,
        scratch_dir=tmp_path,
        controls={"search_radius": -5},
    )
    with pytest.raises(AdapterError, match="search_radius"):
        next(iter(ClassicalWarpAdapter().synthesize(context)))


def test_a_geometry_the_block_size_does_not_divide_still_works():
    """16 does not divide 360. Requiring exact division rejected the P-L spec.

    Caught by an end-to-end render, not by a unit test: validation demanded a
    divisibility the estimator never needed, because it covers whole blocks and
    lets the upsampler's clamp carry the remainder strip.
    """
    height, width = 360, 640
    assert height % 16, "this test is meaningless if the height became divisible"
    rng = np.random.default_rng(3)
    first = rng.integers(0, 256, size=(height, width, 3), dtype=np.uint8)
    second = np.roll(first, 6, axis=1)

    flow = estimate_block_flow(first, second, block_size=16, search_radius=8)
    assert flow.shape == (height // 16, width // 16, 2)
    dense = upsample_flow(flow, height, width, block_size=16)
    assert dense.shape == (height, width, 2)
    assert np.isfinite(dense).all(), "the remainder strip produced non-finite flow"

    frame = interpolate_motion_compensated(first, second, 0.5, flow, flow)
    assert frame.shape == (height, width, 3)
    assert frame.dtype == np.uint8


def test_the_p_l_output_spec_is_accepted_by_the_comparator(tmp_path):
    """The 640x360 delivery geometry must validate, remainder strip and all."""
    anchors = AnchorSet(
        anchors=[
            synthetic_anchor(tmp_path, animation_index=0, anchor_id="s"),
            synthetic_anchor(tmp_path, animation_index=71, anchor_id="e"),
        ]
    )
    report = validate_request(
        make_request(anchors, profile_id="classical-warp-baseline"),
        default_registry(),
        tools=TOOLS,
    )
    assert report.valid, [i.message for i in report.errors]
