"""Frame timing: animation indexing, holds and frame accounting.

Section 12.0 core output: 72 animation frames at 12 animation fps; two-frame
holds form 144 delivery frames at 24 fps and encode exactly six seconds.
Duplicated delivery frames are never reported as new temporal information.
"""

from __future__ import annotations

from collections.abc import Iterator
from fractions import Fraction

from animalite.contracts.assets import AnchorSet
from animalite.contracts.media import FrameAccounting, OutputSpec

__all__ = [
    "animation_index_for_delivery_index",
    "delivery_indices_for_animation_index",
    "exact_duration_seconds",
    "expand_to_delivery",
    "frame_accounting",
]


def delivery_indices_for_animation_index(index: int, output: OutputSpec) -> list[int]:
    """Delivery-stream indices produced by one animation frame."""
    if not 0 <= index < output.animation_frame_count:
        raise IndexError(f"animation index {index} out of range 0..{output.last_animation_index}")
    hold = output.cadence.hold_factor
    start = index * hold
    return list(range(start, start + hold))


def animation_index_for_delivery_index(index: int, output: OutputSpec) -> int:
    """Which animation frame a delivery-stream index shows."""
    if not 0 <= index < output.delivery_frame_count:
        raise IndexError(
            f"delivery index {index} out of range 0..{output.delivery_frame_count - 1}"
        )
    return index // output.cadence.hold_factor


def expand_to_delivery(
    animation_frames: Iterator[bytes] | list[bytes],
    output: OutputSpec,
) -> Iterator[bytes]:
    """Yield the delivery stream by holding each animation frame.

    Frames are yielded, not accumulated: the caller can pipe straight into the
    encoder without holding the whole clip in memory (handoff rule 6).
    """
    hold = output.cadence.hold_factor
    produced = 0
    for animation_index, frame in enumerate(animation_frames):
        if animation_index >= output.animation_frame_count:
            raise ValueError(
                f"adapter produced more than {output.animation_frame_count} animation frames"
            )
        for _ in range(hold):
            yield frame
            produced += 1
    expected_animation = output.animation_frame_count
    if produced != expected_animation * hold:
        raise ValueError(
            f"expected {expected_animation} animation frames expanded to "
            f"{expected_animation * hold} delivery frames; produced {produced}"
        )


def frame_accounting(anchors: AnchorSet, output: OutputSpec) -> FrameAccounting:
    """Count source, synthesized and duplicated frames separately.

    * *source* frames are animation frames that carry an approved anchor.
    * *synthesized* frames are the remaining animation frames.
    * *duplicated* frames are the extra delivery frames created by holds.
    """
    in_range = sum(
        1 for a in anchors.anchors if 0 <= a.animation_index < output.animation_frame_count
    )
    return FrameAccounting(
        animation_frame_count=output.animation_frame_count,
        delivery_frame_count=output.delivery_frame_count,
        source_frame_count=in_range,
        synthesized_frame_count=output.animation_frame_count - in_range,
        duplicated_frame_count=output.delivery_frame_count - output.animation_frame_count,
    )


def exact_duration_seconds(output: OutputSpec) -> Fraction:
    """Exact clip duration as a rational, e.g. ``Fraction(6, 1)`` for the core output."""
    return output.duration_seconds
