"""Regressions for range addressing, fitted eye controls and visible prop contacts."""

from itertools import pairwise

import artwork
import numpy as np
import pytest
from artwork import INSPECTOR_HAND_COLORS
from grip_review import visible_grips
from inspector_art import EYES, HEAD_SIZE, draw_eye
from performance import FRAMES, inspector_eyes, inspector_pose, supported_grips
from PIL import Image, ImageColor
from render import frame_range, native_frames


@pytest.mark.parametrize(("first", "stop"), [(-1, 2), (0, 1), (8, 8), (4, 1), (285, 289)])
def test_invalid_range(first, stop):
    with pytest.raises(ValueError, match="two frames"):
        frame_range(first, stop)


def test_source_frame_addressing():
    frames = list(
        native_frames(640, frame_range(198, 202), inspector_pose, "inspector", "directed")
    )
    sliced = list(
        native_frames(640, frame_range(200, 202), inspector_pose, "inspector", "directed")
    )
    assert sliced == frames[2:]
    assert sliced[0][0] == inspector_pose(200)


def test_eyes_lead_the_recoil_and_close_on_blink():
    down = inspector_eyes(194)
    left = inspector_eyes(201)
    assert down[1] > 0.9 and left[0] < -0.9 and left[1] < 0
    assert abs(inspector_pose(201)[1].angle - inspector_pose(198)[1].angle) < 2

    def pupil(gaze):
        canvas = Image.new("RGBA", HEAD_SIZE)
        draw_eye(canvas, EYES[1][1], *gaze)
        return np.argwhere(
            (np.asarray(canvas)[:, :, :3] == ImageColor.getrgb("#251d1c")).all(axis=2)
        )

    y_down, x_down = pupil(down).mean(axis=0)
    y_left, x_left = pupil(left).mean(axis=0)
    assert x_down > x_left + 4 and y_down > y_left + 3
    assert pupil(inspector_eyes(243)).size == 0


def test_gaze_changes_only_local_eye_pixels():
    _, fixed = next(native_frames(640, [195], inspector_pose, "inspector", "fixed"))
    _, directed = next(native_frames(640, [195], inspector_pose, "inspector", "directed"))
    a, b = (np.frombuffer(raw, dtype=np.uint8).reshape(360, 640, 3) for raw in (fixed, directed))
    y, x = np.where(np.any(a != b, axis=2))
    assert len(x) > 25
    assert np.ptp(x) < 55 and np.ptp(y) < 25


@pytest.mark.parametrize("hidden", ["far hand", "paper"])
def test_fully_occluded_grip_fails_in_actual_composite(hidden, monkeypatch):
    frame = 145

    def composite():
        return next(native_frames(640, [frame], inspector_pose, "inspector", "directed"))

    actors, rgb = composite()
    assert set(visible_grips(rgb, 640, frame, actors, "inspector")) == {
        "milo.near",
        "owner.far",
        "owner.near",
    }
    if hidden == "paper":
        monkeypatch.setattr(artwork, "blueprint", lambda paper: "")
    else:
        draw = artwork.palm

        def skip_far(center, milo, point, color):
            if color == INSPECTOR_HAND_COLORS["owner", 0]:
                return ""
            return draw(center, milo, point, color)

        monkeypatch.setattr(artwork, "palm", skip_far)
    actors, rgb = composite()
    with pytest.raises(ValueError, match=r"Frame 145: .*no readable grip"):
        visible_grips(rgb, 640, frame, actors, "inspector")


def test_inspector_preserves_holds_and_pointing_arc():
    poses = [inspector_pose(f) for f in range(FRAMES)]
    for f, (milo, inspector, paper) in enumerate(poses):
        actors = {"milo": milo, "owner": inspector}
        for (name, hand), grip in supported_grips(f, paper).items():
            assert abs(actors[name].chains[2 + hand].tip - grip) < 1e-8
    elbows = [a.chains[3].joint() for _, a, _ in poses[209:253]]
    assert max(abs(a - b) for a, b in pairwise(elbows)) < 6


def test_godot_midshot_raster_replays_bone_history(tmp_path):
    import shutil
    import time

    from render import godot_frames

    executable = shutil.which("godot")
    if executable is None:
        pytest.skip("Godot executable unavailable in this spike environment")

    def raster(first):
        output = tmp_path / str(first)
        output.mkdir()
        return [
            rgb
            for _, rgb in godot_frames(
                output,
                executable,
                640,
                time.monotonic() + 30,
                frame_range(first, 167),
                inspector_pose,
                "inspector",
                "directed",
            )
        ]

    assert raster(165) == raster(163)[2:]
