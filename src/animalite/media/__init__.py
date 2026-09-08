"""CPU media pipeline: decode, frame timing, streaming encode and output validation."""

from __future__ import annotations

from animalite.media.cadence import (
    animation_index_for_delivery_index,
    delivery_indices_for_animation_index,
    exact_duration_seconds,
    expand_to_delivery,
    frame_accounting,
)
from animalite.media.decode import decode_image_rgb24
from animalite.media.encode import EncodeOutcome, encode_delivery_stream, encoder_argv
from animalite.media.ffmpeg import FFmpegTools, probe_tool
from animalite.media.image import write_png_rgb24
from animalite.media.probe import probe_output, validate_output

__all__ = [
    "EncodeOutcome",
    "FFmpegTools",
    "animation_index_for_delivery_index",
    "decode_image_rgb24",
    "delivery_indices_for_animation_index",
    "encode_delivery_stream",
    "encoder_argv",
    "exact_duration_seconds",
    "expand_to_delivery",
    "frame_accounting",
    "probe_output",
    "probe_tool",
    "validate_output",
    "write_png_rgb24",
]
