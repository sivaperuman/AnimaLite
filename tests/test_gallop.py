"""Studio gallop transfer, camera invariance and reusable drawing contracts."""

import json
from itertools import pairwise
from pathlib import Path

import pytest
from pydantic import ValidationError

from animalite.canine import DogDesign, GallopShot, HeadCue, running_frame
from animalite.cli import main
from animalite.gallop import DogRig
from animalite.story import Storyboard

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "countryside" / "gallop.json"


@pytest.mark.parametrize(
    "rig", [DogRig(), DogRig(shoulder_height=0.81, hip_height=0.78, root_spacing=0.74)]
)
@pytest.mark.parametrize("speed", [2.6, 3.6])
def test_one_gait_transfers_and_keeps_contacts(rig, speed):
    dog = DogDesign(rig=rig)
    action = GallopShot(dog="test", speed=speed)
    frames = [running_frame(action, dog, i, 640) for i in range(96)]
    for direction in ("right", "left"):
        for look in ("ink", "painted-anime"):
            varied = action.model_copy(
                update={"direction": direction, "look": look, "camera_follow": 0.37}
            )
            alt = [running_frame(varied, dog, i, 640) for i in range(96)]
            assert [f.legs for f in frames] == [f.legs for f in alt]
            for prev, cur in pairwise(alt):
                for a, b in zip(prev.legs, cur.legs, strict=True):
                    if a.planted and b.planted:
                        assert a.tip == b.tip
                        dx = cur.screen(b.tip).real - prev.screen(a.tip).real
                        assert dx == pytest.approx(-cur.facing * (cur.camera - prev.camera))
    for i in range(4):
        track = [f.legs[i] for f in frames]
        assert any(limb.planted for limb in track)
        assert all(limb.tip.imag <= 282 for limb in track)
        assert min(limb.tip.imag for limb in track) < 282 - 0.20 * dog.trunk
        excursions = [(limb.tip.real - limb.root.real) / dog.trunk for limb in track]
        assert max(excursions) > 0.35 and min(excursions) < -0.35
    assert any(all(not limb.planted for limb in f.legs) for f in frames)


def test_story_validates_designs_and_view_timing(capsys):
    b = json.loads(EXAMPLE.read_text())
    storyboard = Storyboard.model_validate(b)
    action = storyboard.shots[0].gallop
    assert action
    dog = storyboard.dogs[action.dog]
    assert running_frame(action, dog, 37, 640).head_view == "profile"
    assert running_frame(action, dog, 38, 640).head_view == "three-quarter"
    assert running_frame(action, dog, 62, 640).head_view == "profile"
    assert main(["story-schema"]) == 0
    schema = json.loads(capsys.readouterr().out)
    assert "GallopShot" in schema["$defs"]
    b["shots"][0]["gallop"]["dog"] = "unknown"
    with pytest.raises(ValidationError, match="unknown dog"):
        Storyboard.model_validate(b)
    b["shots"][0]["gallop"]["dog"] = action.dog
    b["shots"][0]["gallop"]["head_cues"] = [{"frame": 96, "view": "profile"}]
    with pytest.raises(ValidationError, match="beyond"):
        Storyboard.model_validate(b)
    with pytest.raises(ValidationError, match="strictly"):
        GallopShot(
            dog="dog",
            head_cues=[HeadCue(frame=3, view="profile"), HeadCue(frame=2, view="profile")],
        )


@pytest.mark.media
def test_rendered_head_cue_and_replay_are_portable(tmp_path, tools, capsys):
    # A deliberately unmistakable replacement drawing makes the encoded cue testable.
    import subprocess

    import numpy as np

    if b"librsvg" not in subprocess.check_output(
        [tools.ffmpeg_path, "-decoders"], stderr=subprocess.DEVNULL
    ):
        pytest.skip("Studio vector decoder unavailable")
    drawing = tmp_path / "look.png"
    subprocess.run(
        [
            tools.ffmpeg_path,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=magenta:s=24x24",
            "-frames:v",
            "1",
            "-threads",
            "1",
            str(drawing),
        ],
        check=True,
    )
    shot = {
        "seconds": 1,
        "action": "Glance",
        "gallop": {"dog": "P", "head_cues": [{"frame": 12, "view": "three-quarter"}]},
    }
    body = {
        "story": "A glance",
        "dogs": {"P": {"head_drawings": {"ink": {"three-quarter": {"image": "look.png"}}}}},
        "shots": [shot],
    }
    source = tmp_path / "board.json"
    source.write_text(json.dumps(body))
    assert main(["story-render", str(source), "--workspace", str(tmp_path / "runs")]) == 0
    movie = Path(capsys.readouterr().out.strip())
    rgb = subprocess.check_output(
        [
            tools.ffmpeg_path,
            "-v",
            "error",
            "-i",
            str(movie),
            "-f",
            "rawvideo",
            "-threads",
            "1",
            "-pix_fmt",
            "rgb24",
            "-",
        ]
    )
    frames = np.frombuffer(rgb, np.uint8).reshape(24, 360, 640, 3)
    magenta = (frames[:, :, :, 0] > 180) & (frames[:, :, :, 1] < 80) & (frames[:, :, :, 2] > 180)
    assert not magenta[:12].any()
    assert all(n > 1000 for n in magenta[12:].sum(axis=(1, 2)))
    drawing.unlink()
    assert (
        main(
            [
                "story-render",
                str(movie.parent / "storyboard.json"),
                "--workspace",
                str(tmp_path / "replay"),
            ]
        )
        == 0
    )
    replay = Path(capsys.readouterr().out.strip())
    assert replay.read_bytes() == movie.read_bytes()
