"""Reusable direction, sequence ownership and evaluated full-body contact."""

import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from animalite.choreography import Contact, Motion, Prop, Target, builtin_moves, validate_contacts
from animalite.contracts.admission import AdmissionPurpose
from animalite.media.probe import probe_output
from animalite.proc import run_capture
from animalite.story import Storyboard, render_story

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/biscuit-handoff.json"


def manifest():
    return json.loads(EXAMPLE.read_bytes())


def test_cast_and_moves_expand_into_replayable_tracks():
    raw = manifest()
    raw["moves"]["double_take"]["right_hand"] = [
        {"frame": 1, "end": 2, "target": {"local": [0, 0, 1]}}
    ]
    board = Storyboard.model_validate(raw)
    stage = board.shots[0].stage
    assert stage is not None
    resolved = board.directed_stage(stage, 144)
    max_actor = resolved.actors["Max"]
    assert max_actor.skin == board.cast["Max"].skin and max_actor.size == 1.02
    assert max_actor.motion and max_actor.motion.head == board.moves["double_take"].head
    assert len(max_actor.motion.right_hand) == 5 and not max_actor.move and not max_actor.design
    assert set(builtin_moves()) == {"peek", "recoil", "offer", "sidestep"}
    # Replaying a resolved shot is independent of the original libraries.
    raw.pop("moves")
    raw.pop("cast")
    raw["shots"][0]["stage"] = resolved.to_json_obj()
    assert Storyboard.model_validate(raw).shots[0].stage == resolved


@pytest.mark.parametrize("alter", ["grip", "actor", "design", "move", "late", "overlap", "preview"])
def test_invalid_direction_is_rejected_before_render(alter):
    raw = manifest()
    stage = raw["shots"][0]["stage"]
    actor = stage["actors"]["Milo"]
    track = actor["motion"]["left_hand"]
    if alter == "grip":
        track[1]["target"]["grip"] = "missing"
    elif alter == "actor":
        track[0]["target"] = {"actor": "nobody"}
    elif alter in ("move", "design"):
        actor[alter] = "missing"
    elif alter == "late":
        track[-1]["end"] = 145
    elif alter == "overlap":
        track[1]["frame"] = 1
    else:
        del stage["cinema"]
    with pytest.raises(ValidationError):
        Storyboard.model_validate(raw)


@pytest.mark.parametrize(
    "target", [{}, {"point": [0, 0, 0], "actor": "A"}, {"local": [0, 0, 0], "grip": "rim"}]
)
def test_ambiguous_destinations(target):
    with pytest.raises(ValidationError):
        Target.model_validate(target)


def test_contact_state_per_hand_and_per_prop():
    props = {n: Prop(kind="ball", position=(0, 0, 1)) for n in ["a", "b"]}

    def event(frame, action, actor, prop="a"):
        return Contact.model_validate(
            {"frame": frame, "action": action, "actor": actor, "hand": "right", "prop": prop}
        )

    take, give, drop = event(2, "grasp", "M"), event(5, "handoff", "X"), event(8, "release", "X")

    def check(events):
        validate_contacts(events, props, {"M", "X"}, 24)

    check([take, give, drop, event(12, "grasp", "M")])
    for bad in [
        [give],
        [take, take],
        [take, event(3, "grasp", "M", "b")],
        [take, event(3, "grasp", "X")],
        [take, event(4, "release", "X")],
        [take, give, event(6, "release", "M")],
        [take, event(25, "handoff", "X")],
    ]:
        with pytest.raises(ValueError):
            check(bad)
    assert Motion.model_validate({"eyes": [{"frame": 2, "end": 2, "target": {"point": [0, 0, 1]}}]})


@pytest.mark.media
def test_blender_solves_contact_and_dynamic_targets_at_every_delivery_frame(tmp_path):
    blender = shutil.which("blender")
    if not blender:
        pytest.skip("optional Blender renderer unavailable")
    board = Storyboard.model_validate(manifest())
    shot = board.shots[0]
    assert shot.stage
    job = {
        "stage": board.directed_stage(shot.stage, 144).to_json_obj(),
        "frames": 144,
        "camera": shot.camera.to_json_obj(),
        "cues": {"Milo": [[int(40 <= f <= 95), 0, 0] for f in range(1, 145)]},
    }
    path = tmp_path / "stage.json"
    path.write_text(json.dumps(job))
    (tmp_path / "step.json").write_text(builtin_moves()["sidestep"].model_dump_json())
    script = ROOT / "tests" / "blender_blocking_checks.py"
    result = run_capture(
        [
            blender,
            "-b",
            "-t",
            "2",
            "--python-exit-code",
            "1",
            "--python",
            str(script),
            "--",
            str(path),
        ],
        timeout=120,
    )
    assert result.returncode == 0, (result.stdout + result.stderr).decode(errors="replace")[-3000:]


@pytest.mark.media
@pytest.mark.slow
def test_move_library_runs_through_movie_export_and_saves_concrete_directions(tmp_path, tools):
    if not shutil.which("blender"):
        pytest.skip("optional Blender renderer unavailable")
    stage = {
        "cinema": {"samples": 1},
        "orbit": {"radius": 8},
        "actors": {m: {"x": (i - 1.5) * 1.3, "move": m} for i, m in enumerate(builtin_moves())},
    }
    path = tmp_path / "input.json"
    path.write_text(
        json.dumps(
            {"story": "Rehearsal", "shots": [{"action": "block", "seconds": 1, "stage": stage}]}
        )
    )
    movie = render_story(
        path, tmp_path / "out", "classical-warp-baseline", AdmissionPurpose.PRODUCTION
    )
    assert probe_output(tools, movie).counted_frames == 24
    saved = Storyboard.model_validate_json((movie.parent / "storyboard.json").read_bytes())
    saved_stage = saved.shots[0].stage
    assert saved_stage
    for name, actor in saved_stage.actors.items():
        assert actor.motion == builtin_moves()[name] and actor.move is None
