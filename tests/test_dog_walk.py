"""Studio action regression checks, including the encoded portrait and vocal gesture."""

import json
import subprocess
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from animalite.cli import main
from animalite.dog_walk import FRAMES, GROUND, LEASH, DogWalk, pose
from animalite.dog_walk_art import project
from animalite.media.probe import probe_output
from animalite.story import Storyboard
from animalite.story_media import Dialogue

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "dog-walk.json"


@pytest.mark.parametrize("launch", [30, 44, 60])
def test_paws_lock_and_leash_holds_through_launch_and_recovery(launch):
    frames = [pose(i, DogWalk(launch_frame=launch)) for i in range(FRAMES)]
    for prev, cur in pairwise(frames):
        for before, after in zip(prev.paws, cur.paws, strict=True):
            if before.planted and after.planted:
                assert before.tip == after.tip
    assert any(not any(paw.planted for paw in p.paws) for p in frames)
    assert all(paw.planted for paw in frames[-1].paws)
    assert frames[-1].seated == frames[-1].look_back == 1
    assert abs(frames[launch].lead.collar - frames[launch].lead.hand) < 0.85 * LEASH
    assert any(max(f.imag for f in p.feet) < GROUND - 60 for p in frames)
    for p in frames:
        points = [p.lead.point(j / 48) for j in range(49)]
        assert abs(sum(abs(b - a) for a, b in pairwise(points)) - LEASH) < 0.02
        assert max(pt.imag for pt in points) < GROUND
        if p.lift == 1:
            assert abs(p.lead.hand - p.lead.collar) == pytest.approx(LEASH)
        for point in (p.face, p.free_hand, *p.feet, p.dog, *points[::8]):
            right = project(p, DogWalk(), point)
            left = project(p, DogWalk(direction="left"), point)
            assert right.real + left.real == pytest.approx(360)
            assert 10 < right.real < 350
            assert right.imag == left.imag


def test_slice_and_source_validation():
    board = json.loads(EXAMPLE.read_text())
    assert Storyboard.model_validate(board).width == 720
    shot = board["shots"][0]
    shot["dog_walk"]["start_frame"] = 1
    with pytest.raises(ValidationError, match="slice exceeds"):
        Storyboard.model_validate(board)
    shot["dog_walk"]["start_frame"] = 0
    shot["stage"] = {"actors": {"Milo": {}}}
    with pytest.raises(ValidationError, match="self-contained"):
        Storyboard.model_validate(board)
    del shot["stage"]
    del shot["dog_walk"]
    shot["seconds"] = 7
    with pytest.raises(ValidationError, match="six seconds"):
        Storyboard.model_validate(board)
    with pytest.raises(ValidationError, match="vocalization"):
        Dialogue.model_validate({"character": "Milo", "text": "hello", "vocalization": "sigh"})


@pytest.mark.media
@pytest.mark.slow
def test_portrait_slices_replay_sigh_and_visible_leash(tmp_path, tools, capsys):
    decoders = subprocess.check_output([tools.ffmpeg_path, "-decoders"], stderr=subprocess.DEVNULL)
    if b"librsvg" not in decoders:
        pytest.skip("PENDING: Studio vector rendering requires FFmpeg's librsvg decoder")
    board = json.loads(EXAMPLE.read_text())
    board["height"] = 640
    shot = board["shots"][0]
    shot.update(
        seconds=1,
        dog_walk={"direction": "left", "start_frame": 71},
        dialogue=[{"character": "Milo", "start_ms": 0, "vocalization": "sigh"}],
    )
    board["shots"].append(
        {**shot, "dialogue": [], "dog_walk": {"direction": "left", "start_frame": 95}}
    )
    manifest = tmp_path / "board.json"
    manifest.write_text(json.dumps(board))
    assert main(["story-render", str(manifest), "--workspace", str(tmp_path)]) == 0
    movie = Path(capsys.readouterr().out.strip())
    probe = probe_output(tools, movie)
    assert (probe.width, probe.height, probe.counted_frames) == (360, 640, 48)
    replay = Storyboard.model_validate_json((movie.parent / "storyboard.json").read_bytes())
    tracks = [
        json.loads(line)
        for clip in (1, 2)
        for line in (movie.parent / f"dog-walk-{clip}" / "contacts.jsonl").read_text().splitlines()
    ]
    assert [record["action_frame"] for record in tracks] == list(range(71, 119))
    assert all(record["canvas_px"] == [360, 640] for record in tracks)
    assert all(len(record["paws_px"]) == 4 and "hip" in record["handler_px"] for record in tracks)
    line = replay.shots[0].dialogue[0]
    assert line.vocalization is None and line.audio is not None
    assert (movie.parent / line.audio).is_file()
    rgb = subprocess.check_output(
        [
            tools.ffmpeg_path,
            "-v",
            "error",
            "-i",
            str(movie),
            "-an",
            "-pix_fmt",
            "rgb24",
            "-f",
            "rawvideo",
            "-threads",
            "1",
            "-",
        ]
    )
    images = np.frombuffer(rgb, dtype=np.uint8).reshape((48, 640, 360, 3))
    action = DogWalk(direction="left")
    for i, img in enumerate(images):
        p = pose(71 + i, action)
        for u in (0.06, 0.25, 0.5, 0.75, 0.94):
            pt = project(p, action, p.lead.point(u))
            x, y = round(pt.real), round(pt.imag)
            patch = img[y - 2 : y + 3, x - 2 : x + 3].astype(int)
            # The decoded warm-red lead must be visible at its predicted position.
            red, green, blue = patch[:, :, 0], patch[:, :, 1], patch[:, :, 2]
            assert np.any((red > 160) & (red - green > 72) & (green - blue > 8)), (i, u)


def test_fall_separates_the_lead_drop_impact_and_recovery():
    action = DogWalk(performance="fall-and-recover")
    start, loose, flight, impact, hold, seated = [
        pose(i, action) for i in (0, 24, 72, 148, 167, 188)
    ]
    for state in (start, loose, flight, impact, hold, seated):
        assert state.fall is not None
        face = project(state, action, state.face)
        assert face == pytest.approx(state.fall.body.face * 2.5)
    assert start.camera_x == loose.camera_x < flight.camera_x < impact.camera_x
    assert (
        loose.fall
        and loose.fall.slack == 1
        and loose.fall.lead_end.imag > loose.fall.body.grip.imag + 45
    )
    assert flight.lift == 1 and flight.fall and flight.fall.lead_end == flight.fall.body.grip
    assert impact.fall and hold.fall and impact.fall.prone == hold.fall.prone == 1
    assert impact.fall.release == 1 and impact.seated == hold.seated == 0
    assert (
        hold.fall.body.face.imag > 185
        and abs(hold.fall.body.hip.imag - hold.fall.body.neck.imag) < 8
    )
    assert seated.seated == 1 and seated.fall and seated.fall.body.face.imag < 137
    assert impact.camera_x == hold.camera_x == seated.camera_x


def test_fall_paw_world_contacts_and_vector_attachment():
    frames = [pose(i, DogWalk(performance="fall-and-recover")) for i in range(FRAMES)]
    for state in frames:
        assert state.lead.collar == state.dog + complex(17, -12)
    for before, after in pairwise(frames):
        for first, second in zip(before.paws, after.paws, strict=True):
            if first.planted and second.planted:
                assert first.tip == second.tip
