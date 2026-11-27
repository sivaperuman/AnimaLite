"""Reference-guided running keeps world contacts while transferring pose and timing."""

import json
from itertools import pairwise
from pathlib import Path

import pytest
from pydantic import ValidationError

from animalite.canine import running_frame
from animalite.story import Storyboard
from animalite.story_edit import ShotEdit, apply_edit

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.mark.parametrize("name", ["Clover", "Reed"])
@pytest.mark.parametrize("direction", ["left", "right"])
def test_pose_transfer_and_front_footprints(name, direction):
    board = Storyboard.model_validate_json((EXAMPLES / "leash-run/story.json").read_bytes())
    source = board.shots[1].gallop
    assert source
    resolved = board.directed_gallop(source)
    assert resolved.performance and resolved.performance.pose_guide
    dog = (
        board.dogs["Clover"]
        if name == "Clover"
        else Storyboard.model_validate_json(
            (EXAMPLES / "countryside/gallop.json").read_bytes()
        ).dogs["Reed"]
    )
    shot = resolved.model_copy(update={"direction": direction, "dog": name})
    old = shot.model_copy(
        update={"performance": resolved.performance.model_copy(update={"pose_guide": None})}
    )
    for acceleration in (5, 7):
        perf = resolved.performance.model_copy(update={"acceleration_frames": acceleration})
        frames = [
            running_frame(shot.model_copy(update={"performance": perf}), dog, i, 640)
            for i in range(144)
        ]
        peak = perf.launch_frame + acceleration
        reach = frames[peak].legs[3]
        ratio = abs(reach.ankle - reach.root) / (
            abs(reach.joint - reach.root) + abs(reach.ankle - reach.joint)
        )
        assert ratio > 0.98
        assert not reach.planted
        landed = next(i for i in range(peak, len(frames)) if frames[i].legs[3].planted)
        assert landed == perf.first_touch_frame(resolved.performance.pose_guide)
        assert frames[landed].legs[3].tip.imag == frames[landed].floor_y
        if acceleration == 7:
            original = running_frame(old, dog, peak, 640).legs[3]
            assert (reach.tip - reach.root).real > (original.tip - original.root).real
        front = [f for f in frames if 0.36 <= f.turn <= 0.64]
        assert front
        for f in frames:
            if f.stage == "turn":
                for far, near in ((0, 2), (1, 3)):
                    a, b = f.legs[far], f.legs[near]
                    assert (b.root.real - a.root.real) * (b.tip.real - a.tip.real) >= 0
        for f in front:
            for far, near in ((0, 2), (1, 3)):
                assert f.legs[far].tip.real < f.body.real < f.legs[near].tip.real
                assert f.legs[far].root.real < f.legs[near].root.real
        contacts = [
            abs(a.tip - b.tip)
            for prev, cur in pairwise(frames)
            for a, b in zip(prev.legs, cur.legs, strict=True)
            if a.planted and b.planted
        ]
        assert contacts and max(contacts) < 1e-8


def test_reference_validation_and_identity_at_zero_weight():
    board = Storyboard.model_validate_json((EXAMPLES / "leash-run/story.json").read_bytes())
    shot = board.shots[1].gallop
    assert shot
    resolved = board.directed_gallop(shot)
    perf = resolved.performance
    assert perf and perf.pose_guide
    old = resolved.model_copy(update={"performance": perf.model_copy(update={"pose_guide": None})})
    guide = perf.pose_guide.model_dump()
    for name in ("reach", "landing"):
        guide[name]["strength"] = 0
    guide["front_strength"] = 0
    edited = apply_edit(board, ShotEdit.model_validate({"shot": 2, "pose_guide": guide}))
    new = edited.shots[1].gallop
    assert new and not new.guide_name and new.performance
    for i in range(144):
        assert running_frame(new, board.dogs["Clover"], i, 640) == running_frame(
            old, board.dogs["Clover"], i, 640
        )
    guide["reach"]["wrist"] = guide["reach"]["elbow"]
    with pytest.raises(ValidationError, match="distinct"):
        ShotEdit.model_validate({"shot": 2, "pose_guide": guide})
    with pytest.raises(ValidationError, match="unknown gallop guide"):
        apply_edit(board, ShotEdit(shot=2, guide_name="absent"))
    with pytest.raises(ValidationError, match="landing must precede"):
        apply_edit(board, ShotEdit(shot=2, brake_frame=26))


@pytest.mark.media
def test_leg_atlas_is_drawn_and_replayed(tmp_path, tools, capsys):
    import subprocess

    from animalite.cli import main

    if b"librsvg" not in subprocess.check_output(
        [tools.ffmpeg_path, "-decoders"], stderr=subprocess.DEVNULL
    ):
        pytest.skip("librsvg unavailable")
    source = tmp_path / "board.json"
    board = {
        "story": "painted legs",
        "dogs": {"dog": {"leg_drawing": {"image": str(EXAMPLES / "leash-run/tan-paws.png")}}},
        "shots": [
            {"seconds": 1, "action": "run", "gallop": {"look": "painted-anime", "dog": "dog"}}
        ],
    }

    def render(path):
        assert main(["story-render", str(path), "--workspace", str(tmp_path / "runs")]) == 0
        return Path(capsys.readouterr().out.strip())

    source.write_text(json.dumps(board))
    new = render(source)
    saved = json.loads((new.parent / "storyboard.json").read_text())
    asset = saved["dogs"]["dog"]["leg_drawing"]["image"]
    assert asset in json.loads((new.parent / "shot-index.json").read_text())["digests"]
    assert new.read_bytes() == render(new.parent / "storyboard.json").read_bytes()
    board["dogs"] = {"dog": {}}
    source.write_text(json.dumps(board))
    old = render(source)
    assert old.read_bytes() != new.read_bytes()
    assert (old.parent / "gallop-1/contacts.jsonl").read_bytes() == (
        new.parent / "gallop-1/contacts.jsonl"
    ).read_bytes()
