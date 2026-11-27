"""Finished-picture review regressions at the S1 shot cadence."""

import time

import numpy as np
import pytest
from PIL import Image
from take_review import decoded_review, picture_notes, review_frames

from animalite.media.ffmpeg import FFmpegTools
from animalite.proc import run_capture


def test_brief_flash_and_sustained_cut_have_different_signatures():
    gray = np.full((20, 4, 4), 75, dtype=np.uint8)
    gray[7] = 220
    gray[12:] = 140
    assert picture_notes(gray, 130) == [
        {"kind": "flash_candidate", "start_frame": 137, "stop_frame": 138}
    ]


def test_low_light_with_detail_and_short_comic_holds():
    dark = np.zeros((12, 4, 4), dtype=np.uint8)
    dark[:, :, ::2] = 42
    assert picture_notes(dark, 0) == []
    assert picture_notes(dark[:2], 286) == []


def test_contact_sheet_bounds_and_merges_flags_with_beats():
    notes = [{"kind": "edge_jump", "start_frame": f} for f in range(197, 204)]
    labels = review_frames(range(197, 205), notes)
    assert list(labels) == [197, 198, 199, 200, 201, 204]
    assert labels[197] == "Read the drawing / edge jump"


@pytest.mark.media
def test_decoded_clip_observations_and_frame_addressing(tmp_path):
    tools = FFmpegTools.discover()
    if not tools.available:
        pytest.skip(tools.unavailable_reason)
    # 48 silent grayscale frames with a flash, a black interval and a trailing hold.
    levels = np.arange(48, dtype=np.uint8) * 2 + 60
    levels[0] = 255
    levels[10:18] = 0
    levels[24:] = levels[23]
    raw = tmp_path / "lighting.gray"
    raw.write_bytes(np.broadcast_to(levels[:, None, None], (48, 36, 64)).tobytes())
    movie = tmp_path / "shot.mp4"
    encode = run_capture(
        [
            tools.ffmpeg_path,
            "-nostdin",
            "-v",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "-s",
            "64x36",
            "-framerate",
            "24",
            "-i",
            str(raw),
            "-c:v",
            "libx264",
            "-threads",
            "1",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "0",
            str(movie),
        ],
        timeout=20,
    )
    assert encode.returncode == 0 and not encode.survivors
    sheet = tmp_path / "sheet.webp"
    review = decoded_review(tools.ffmpeg_path, movie, range(165, 213), sheet, time.monotonic() + 15)
    assert review["findings"] == [
        {"kind": "edge_jump", "start_frame": 165, "stop_frame": 166},
        {"kind": "near_black", "start_frame": 175, "stop_frame": 183},
        {"kind": "near_still", "start_frame": 188, "stop_frame": 213},
    ]
    with Image.open(sheet) as picture:
        assert picture.getpixel((100, 60))[0] > 240
        assert picture.getpixel((356, 60))[0] < 10
    for stop in (212, 214):
        with pytest.raises(ValueError, match="frames"):
            decoded_review(tools.ffmpeg_path, movie, range(165, stop), sheet, time.monotonic() + 15)
