"""Storyboard timing, input resolution and verified multi-shot delivery."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from animalite.cli import main
from animalite.media.probe import probe_output
from animalite.story import Pose, Storyboard, StoryShot


def test_pose_indices_must_cover_the_shot_in_order():
    for indices in ([0, 1, 1, 11], [1, 11], [0, 12], [0, 7, 4, 11]):
        with pytest.raises(ValidationError, match="increase strictly"):
            StoryShot(
                action="turn",
                seconds=1,
                poses=[Pose(image=Path("pose.png"), frame=frame) for frame in indices],
            )


@pytest.mark.media
@pytest.mark.slow
def test_story_resolves_relative_images_joins_shots_and_keeps_replayable_inputs(
    tmp_path, preview_anchors, tools, capsys
):
    images = []
    for i, anchor in enumerate(preview_anchors.anchors):
        image = Path(f"pose {i}.png")
        (tmp_path / image).write_bytes(Path(anchor.asset.path).read_bytes())
        images.append(image)
    shots = [
        StoryShot(
            action="move",
            seconds=seconds,
            timing="ease-in-out",
            poses=[Pose(image=images[0], frame=0), Pose(image=images[1], frame=12 * seconds - 1)],
        )
        for seconds in (1, 2)
    ]
    board = tmp_path / "story.json"
    board.write_text(Storyboard(story="two cuts", shots=shots).model_dump_json())
    ws = tmp_path / "workspace"
    cmd = [
        "story-render",
        str(board),
        "--workspace",
        str(ws),
        "--profile",
        "classical-warp-baseline",
    ]
    assert main(cmd) == 0
    movie = Path(capsys.readouterr().out.strip())
    probe = probe_output(tools, movie)
    assert (probe.width, probe.height, probe.counted_frames, probe.duration_seconds) == (
        640,
        360,
        72,
        3.0,
    )
    replay = Storyboard.model_validate_json((movie.parent / "storyboard.json").read_bytes())
    assert all(
        (movie.parent / pose.image).is_file() for shot in replay.shots for pose in shot.poses
    )
    (tmp_path / images[0]).unlink()
    assert main(cmd) != 0
    assert "file" in capsys.readouterr().err.lower()
    assert list(ws.glob("*/story.mp4")) == [movie]
