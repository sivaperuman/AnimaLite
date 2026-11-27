"""Acceptance checks for joined actions, contact-driven acting, painted turns and revisions."""

import json
from itertools import pairwise
from pathlib import Path

import pytest
from pydantic import ValidationError

from animalite.canine import DogDesign, GallopShot, running_frame
from animalite.cli import main
from animalite.dog_action import RunAction
from animalite.dog_handler import LeadPerformance
from animalite.errors import ValidationRejected
from animalite.story import Storyboard
from animalite.story_edit import ShotEdit, apply_edit, from_instruction

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/leash-run/story.json"


def test_motion_contacts_and_leash_retime():
    board = Storyboard.model_validate_json(EXAMPLE.read_bytes())
    g = board.shots[1].gallop
    assert g and g.handler and g.performance
    d = board.dogs[g.dog]
    a = g.performance
    onsets = []
    for launch in (a.launch_frame, a.launch_frame + 8):
        shot = g.model_copy(update={"performance": a.model_copy(update={"launch_frame": launch})})
        actor = LeadPerformance(g.handler, board.cast[g.handler.actor])
        frames = [running_frame(shot, d, i, 640) for i in range(144)]
        handlers = [actor.advance(f, d, i) for i, f in enumerate(frames)]
        assert all(f.body == frames[0].body for f in frames[: launch + 1])
        assert frames[-1].yaw == -1 and all(leg.planted for leg in frames[-1].legs)
        assert {f.stage for f in frames} == {"stand", "launch", "gallop", "brake", "turn", "settle"}
        for previous, current in pairwise(frames):
            for leg, r in zip(previous.legs, current.legs, strict=True):
                if leg.planted and r.planted:
                    assert leg.tip == pytest.approx(r.tip, abs=1e-9)
        assert any(all(not leg.planted for leg in f.legs) for f in frames)
        assert {f.body_key() for f in frames} == set(d.body_drawings)
        assert any(f.stretch < 0.95 for f in frames) and any(f.stretch > 1.05 for f in frames)
        onsets.append(next(i for i, h in enumerate(handlers) if h.tension > 0.65))
        for f, h in zip(frames, handlers, strict=True):
            assert h.lead.point(0) == h.lead.hand and h.lead.point(1) == f.collar(d)
            pts = [h.lead.point(n / 48) for n in range(49)]
            assert sum(abs(x - y) for x, y in pairwise(pts)) == pytest.approx(
                g.handler.leash_length * f.length, abs=0.08
            )
        assert max(h.lift for h in handlers) > 0.9 and handlers[-1].lift < 0.005
        assert handlers[0].surprise == 0
    assert onsets[1] - onsets[0] == 8


def test_directions_design_identity_and_validation():
    board = Storyboard.model_validate_json(EXAMPLE.read_bytes())
    g = board.shots[2].gallop
    assert g
    dog = board.dogs[g.dog]
    for i in range(144):
        f = running_frame(g, dog, i, 640)
        other = running_frame(
            g.model_copy(update={"look": "painted-anime", "direction": "left"}), dog, i, 640
        )
        assert f.legs == other.legs and f.body_key() == other.body_key()
        assert f.screen(f.collar(dog)).real + other.screen(other.collar(dog)).real == pytest.approx(
            640
        )
    edit = from_instruction(board, 2, "make the launch quicker and hold the surprised look longer")
    revised = apply_edit(board, edit)
    assert revised.dogs == board.dogs and revised.cast == board.cast
    assert revised.shots[0] == board.shots[0] and revised.shots[2] == board.shots[2]
    with pytest.raises(ValidationError, match="beyond"):
        apply_edit(board, ShotEdit(shot=2, turn_frames=200))
    with pytest.raises(ValidationRejected, match="unsupported"):
        from_instruction(board, 2, "replace the dog")
    with pytest.raises(ValidationError, match="body_drawings"):
        DogDesign(body_drawings={"front": dog.body_drawings["front"]})
    with pytest.raises(ValidationError, match="before braking"):
        RunAction(launch_frame=20, acceleration_frames=9, brake_frame=21, braking_frames=8)


@pytest.mark.media
def test_revise_renders_only_selected_shot_and_keeps_audio(tmp_path, tools, capsys, monkeypatch):
    import subprocess

    import animalite.story_edit as editing
    from animalite.canine_render import render_gallop

    if b"librsvg" not in subprocess.check_output(
        [tools.ffmpeg_path, "-decoders"], stderr=subprocess.DEVNULL
    ):
        pytest.skip("librsvg unavailable")
    g = GallopShot(
        dog="P",
        performance=RunAction(
            launch_frame=1, acceleration_frames=3, brake_frame=9, braking_frames=3, turn_frames=6
        ),
    )
    s = {"seconds": 1, "action": "sprint", "gallop": g.to_json_obj()}
    board = {
        "story": "two takes",
        "dogs": {"P": {}},
        "shots": [dict(s, dialogue=[{"character": "P", "vocalization": "sigh"}]), s],
    }
    fname = tmp_path / "board.json"
    fname.write_text(json.dumps(board))
    assert main(["story-render", str(fname), "--workspace", str(tmp_path)]) == 0
    original = Path(capsys.readouterr().out.strip()).parent
    calls = []
    native = render_gallop

    def capture(*args, **kwargs):
        calls.append(args[7].name)
        return native(*args, **kwargs)

    monkeypatch.setattr(editing, "render_gallop", capture)
    edit = tmp_path / "edit.json"
    edit.write_text('{"shot":2,"speed":4}')
    args = ["story-revise", str(original), "--workspace", str(tmp_path), "--edit", str(edit)]
    assert main(args) == 0
    run = Path(capsys.readouterr().out.strip()).parent
    assert calls == ["gallop-2"] and run != original
    for name in ("gallop-1/shot.mp4", "gallop-1/contacts.jsonl", "dialogue.wav"):
        assert (run / name).read_bytes() == (original / name).read_bytes()
    assert (run / "gallop-2/shot.mp4").read_bytes() != (original / "gallop-2/shot.mp4").read_bytes()
    assert main(["story-render", str(run / "storyboard.json"), "--workspace", str(tmp_path)]) == 0
    assert Path(capsys.readouterr().out.strip()).read_bytes() == (run / "story.mp4").read_bytes()
    (original / "gallop-1/shot.mp4").write_bytes(b"changed clip")
    assert main(args) != 0 and calls == ["gallop-2"]
