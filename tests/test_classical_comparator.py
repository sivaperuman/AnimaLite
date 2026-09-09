"""The classical warp/flow comparator: it must work, and it must never qualify.

Ground truth is constructed rather than eyeballed. A known translation gives a
frame we can demand back, so "does motion compensation actually happen" is a
measurement instead of an impression.
"""

from __future__ import annotations

import time

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
from animalite.errors import AdapterError, CodeVAL, JobCancelled, JobTimeoutError
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


def test_motion_beyond_the_search_radius_is_reported_wrong_rather_than_as_zero():
    """The zero incumbent does NOT make out-of-range motion report no motion.

    An earlier version of this file claimed it did. It does not: on textured
    content a within-window candidate usually still beats standing still, so it
    is accepted, and the result is a confident wrong displacement. Measured on a
    deterministic 64x96 random texture translated 24 px and searched at radius 4,
    95 of 96 blocks returned nonzero flow.

    This is the ambiguity documented rather than designed around. What the
    estimator does guarantee is the bound, which is a different and much weaker
    property than detection -- asserted separately below so the two are not
    confused again.
    """
    rng = np.random.default_rng(11)
    height, width, shift = 64, 96, 24
    base = rng.integers(0, 256, size=(height, width + shift, 3), dtype=np.uint8)
    first = np.ascontiguousarray(base[:, :width])
    second = np.ascontiguousarray(base[:, shift : shift + width])

    flow = estimate_block_flow(first, second, block_size=8, search_radius=4)
    blocks = flow.shape[0] * flow.shape[1]
    nonzero = int(np.count_nonzero(flow.any(axis=2)))
    assert nonzero > blocks * 0.9, (
        f"only {nonzero}/{blocks} blocks reported motion; if this estimator has "
        "become able to detect out-of-range motion, the documented limitation in "
        "media/flow.py and DEC-0015 needs updating rather than this assertion"
    )
    assert np.abs(flow).max() <= 4, "the estimator exceeded its own search radius"


def test_an_unmatchable_region_reports_no_motion_only_when_it_is_flat():
    """The zero incumbent works where there is nothing to match, and only there."""
    first, _middle, second = _textured_pair(shift=60)
    flow = estimate_block_flow(first, second, search_radius=8)
    assert np.abs(flow).max() <= 8, "the estimator exceeded its own search radius"
    flat = np.full((64, 64, 3), 128, dtype=np.uint8)
    other = np.full((64, 64, 3), 130, dtype=np.uint8)
    assert not np.any(estimate_block_flow(flat, other, search_radius=8))


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
    assert any("cannot, on its own, identify the mechanism" in note for note in caps.notes)
    assert any("confident, wrong displacements" in note for note in caps.notes)


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
        # 0.5 validated and then truncated to a radius-0 search.
        ({"search_radius": 0.5}, CodeVAL.CONTROL_VALUE_INVALID),
        ({"block_size": 16.5}, CodeVAL.CONTROL_VALUE_INVALID),
        # float(10**1000) raises OverflowError; it escaped validation entirely.
        ({"search_radius": 10**1000}, CodeVAL.CONTROL_VALUE_INVALID),
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
        tools=TOOLS,
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


# --- cancellation reaches inside the search ----------------------------------


def test_the_search_calls_its_checkpoint_and_an_exception_abandons_it():
    """Full search at radius 16 takes seconds; it has to be interruptible.

    Checking only between animation frames meant a cancel arriving during the
    first search waited for the whole search to finish.
    """
    calls: list[int] = []

    def checkpoint() -> None:
        calls.append(len(calls))
        if len(calls) > 3:
            raise KeyboardInterrupt("stop here")

    first, _middle, second = _textured_pair(width=128, height=64)
    with pytest.raises(KeyboardInterrupt):
        estimate_block_flow(first, second, search_radius=16, checkpoint=checkpoint)
    assert len(calls) == 4, "the search ran past its checkpoint"


def test_cancellation_during_the_flow_search_stops_the_comparator(tmp_path):
    """At the adapter level: the cancel is observed inside the search, not after."""
    first, _middle, second = _textured_pair(width=320, height=180)
    anchors = AnchorSet(
        anchors=[
            synthetic_anchor(tmp_path, animation_index=0, anchor_id="s", width=320, height=180),
            synthetic_anchor(tmp_path, animation_index=3, anchor_id="e", width=320, height=180),
        ]
    )
    context = AdapterContext(
        anchor_frames={0: first, 3: second},
        output=P_L_FINAL_OUTPUT.model_copy(
            update={"width": 320, "height": 180, "animation_frame_count": 4}
        ),
        anchors=anchors,
        profile=CLASSICAL_WARP_PROFILE,
        scratch_dir=tmp_path,
        tools=TOOLS,
        cancel=lambda: True,
    )
    with pytest.raises(JobCancelled):
        list(ClassicalWarpAdapter().synthesize(context))


def test_an_expired_deadline_stops_the_comparator(tmp_path):
    first, _middle, second = _textured_pair(width=320, height=180)
    anchors = AnchorSet(
        anchors=[
            synthetic_anchor(tmp_path, animation_index=0, anchor_id="s", width=320, height=180),
            synthetic_anchor(tmp_path, animation_index=3, anchor_id="e", width=320, height=180),
        ]
    )
    context = AdapterContext(
        anchor_frames={0: first, 3: second},
        output=P_L_FINAL_OUTPUT.model_copy(
            update={"width": 320, "height": 180, "animation_frame_count": 4}
        ),
        anchors=anchors,
        profile=CLASSICAL_WARP_PROFILE,
        scratch_dir=tmp_path,
        tools=TOOLS,
        deadline=time.monotonic() - 0.001,
    )
    with pytest.raises(JobTimeoutError):
        list(ClassicalWarpAdapter().synthesize(context))


def test_the_comparator_needs_no_execution_admission():
    """Admission is for executing third-party model artifacts. This has none."""
    from animalite.admission import evaluate_admission
    from animalite.contracts.admission import AdmissionPurpose

    outcome = evaluate_admission(CLASSICAL_WARP_PROFILE, AdmissionPurpose.BENCHMARK)
    assert outcome.admitted
    assert outcome.state == "not_required"
