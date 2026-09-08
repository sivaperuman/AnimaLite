"""Frame timing: the section 12.0 core output contract must hold exactly."""

from __future__ import annotations

from fractions import Fraction

import pytest

from animalite.contracts.assets import AnchorSet
from animalite.contracts.enums import CadenceConversion
from animalite.contracts.media import (
    P_L_FINAL_OUTPUT,
    PREVIEW_OUTPUT,
    CadencePolicy,
    FrameAccounting,
    OutputSpec,
)
from animalite.media.cadence import (
    animation_index_for_delivery_index,
    delivery_indices_for_animation_index,
    expand_to_delivery,
    frame_accounting,
)
from tests.conftest import synthetic_anchor


def test_core_output_is_exactly_six_seconds():
    out = P_L_FINAL_OUTPUT
    assert (out.width, out.height) == (640, 360)
    assert out.animation_frame_count == 72
    assert out.cadence.animation_fps == 12
    assert out.cadence.delivery_fps == 24
    assert out.cadence.hold_factor == 2
    assert out.delivery_frame_count == 144
    # Exact rational equality, not a float tolerance.
    assert out.duration_seconds == Fraction(6, 1)
    assert out.last_animation_index == 71


def test_preview_output_is_exactly_three_seconds():
    out = PREVIEW_OUTPUT
    assert (out.width, out.height) == (320, 180)
    assert out.animation_frame_count == 36
    assert out.delivery_frame_count == 72
    assert out.duration_seconds == Fraction(3, 1)
    assert out.aspect_ratio == P_L_FINAL_OUTPUT.aspect_ratio


def test_two_frame_holds_map_animation_to_delivery():
    out = P_L_FINAL_OUTPUT
    assert delivery_indices_for_animation_index(0, out) == [0, 1]
    assert delivery_indices_for_animation_index(71, out) == [142, 143]
    assert animation_index_for_delivery_index(0, out) == 0
    assert animation_index_for_delivery_index(1, out) == 0
    assert animation_index_for_delivery_index(143, out) == 71
    # Every delivery index maps back into the animation stream exactly once.
    covered = [
        idx
        for animation in range(out.animation_frame_count)
        for idx in delivery_indices_for_animation_index(animation, out)
    ]
    assert covered == list(range(out.delivery_frame_count))


@pytest.mark.parametrize("index", [-1, 72])
def test_out_of_range_animation_index_is_rejected(index):
    with pytest.raises(IndexError):
        delivery_indices_for_animation_index(index, P_L_FINAL_OUTPUT)


def test_expand_to_delivery_holds_each_frame_and_counts():
    out = OutputSpec(width=16, height=16, animation_frame_count=3)
    frames = [b"a", b"b", b"c"]
    assert list(expand_to_delivery(frames, out)) == [b"a", b"a", b"b", b"b", b"c", b"c"]


def test_expand_to_delivery_rejects_a_short_adapter_stream():
    out = OutputSpec(width=16, height=16, animation_frame_count=3)
    with pytest.raises(ValueError, match="expected 3 animation frames"):
        list(expand_to_delivery([b"a", b"b"], out))


def test_expand_to_delivery_rejects_an_over_long_adapter_stream():
    out = OutputSpec(width=16, height=16, animation_frame_count=2)
    with pytest.raises(ValueError, match="more than 2 animation frames"):
        list(expand_to_delivery([b"a", b"b", b"c"], out))


def test_frame_accounting_separates_source_synthesized_and_duplicated(tmp_path):
    anchors = AnchorSet(
        anchors=[
            synthetic_anchor(tmp_path, animation_index=0, anchor_id="s"),
            synthetic_anchor(tmp_path, animation_index=35, anchor_id="m"),
            synthetic_anchor(tmp_path, animation_index=71, anchor_id="e"),
        ]
    )
    counts = frame_accounting(anchors, P_L_FINAL_OUTPUT)
    assert counts.source_frame_count == 3
    assert counts.synthesized_frame_count == 69
    assert counts.source_frame_count + counts.synthesized_frame_count == 72
    # Duplicated frames are the holds only; they are never new temporal information.
    assert counts.duplicated_frame_count == 72
    assert counts.delivery_frame_count == 144


def test_frame_accounting_totals_are_enforced():
    with pytest.raises(ValueError, match="must equal animation_frame_count"):
        FrameAccounting(
            animation_frame_count=72,
            delivery_frame_count=144,
            source_frame_count=2,
            synthesized_frame_count=69,
            duplicated_frame_count=72,
        )
    with pytest.raises(ValueError, match="duplicated_frame_count must equal"):
        FrameAccounting(
            animation_frame_count=72,
            delivery_frame_count=144,
            source_frame_count=2,
            synthesized_frame_count=70,
            duplicated_frame_count=0,
        )


def test_duplicate_cadence_requires_an_integer_multiple():
    with pytest.raises(ValueError, match="integer multiple"):
        CadencePolicy(animation_fps=12, delivery_fps=25)


def test_hold_factor_is_undefined_for_interpolated_uplift():
    policy = CadencePolicy(
        animation_fps=12, delivery_fps=24, conversion=CadenceConversion.INTERPOLATE
    )
    with pytest.raises(ValueError, match="only defined for cadence_conversion 'duplicate'"):
        _ = policy.hold_factor


def test_yuv420p_requires_even_dimensions():
    with pytest.raises(ValueError, match="requires even dimensions"):
        OutputSpec(width=641, height=360, animation_frame_count=72)
