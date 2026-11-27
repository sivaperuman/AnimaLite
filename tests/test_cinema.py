"""Cinematic storyboard contracts, actual Blender scene evaluation and video delivery."""

import json
import shutil
import struct
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from animalite.contracts.admission import AdmissionPurpose
from animalite.media.probe import probe_output
from animalite.performance import Actor, Cinema, Stage
from animalite.proc import run_capture
from animalite.story import Storyboard, render_story
from animalite.story_media import Camera
from tests.test_performance import gray_frames

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "workshop-reaction.json"


@pytest.mark.parametrize(
    "acting",
    [
        [{"at": 0.2}, {"at": 0.2}],
        [{"at": 0.8}, {"at": 0.4}],
        [{"at": 1.01}],
        [{"at": 0, "blink": -1}],
        [{"at": 0, "head_turn": 2}],
        [{"at": 0, "squash": float("nan")}],
    ],
)
def test_pose_limits(acting):
    with pytest.raises(ValidationError):
        Actor.model_validate({"acting": acting})


@pytest.mark.parametrize(
    "config",
    [
        {"samples": 0},
        {"samples": 129},
        {"lighting": "bogus"},
        {"f_stop": 0.1},
        {"focus_distance": [1, 0]},
        {"shutter": 1.1},
    ],
)
def test_cinema_limits(config):
    with pytest.raises(ValidationError):
        Cinema.model_validate(config)


def test_stages_validate_their_controls_and_round_trip():
    board = Storyboard.model_validate_json(EXAMPLE.read_bytes())
    assert Storyboard.model_validate_json(board.model_dump_json()) == board
    old = Stage.model_validate({"actors": {"Milo": {}}})
    assert Stage.model_validate_json(old.model_dump_json()) == old
    for actor in [{"costume": "cap"}, {"acting": [{"at": 0}]}]:
        with pytest.raises(ValidationError, match=r"require stage\.cinema"):
            Stage.model_validate({"actors": {"Milo": actor}})
    with pytest.raises(ValidationError, match="requires a GLB"):
        Stage.model_validate({"actors": {"Milo": {}}, "cinema": {"set": "asset"}})
    assert Stage.model_validate({"model": "set.glb", "cinema": {"set": "asset"}}).cinema
    flat = {
        "action": "wave",
        "seconds": 1,
        "poses": [{"frame": 0, "image": "a.png"}, {"frame": 11, "image": "b.png"}],
    }
    with pytest.raises(ValidationError, match="native HD"):
        Storyboard.model_validate(
            {"story": "HD", "height": 720, "shots": [board.shots[0].to_json_obj(), flat]}
        )


@pytest.mark.media
def test_evaluated_camera_poses_materials_and_mouth_keys(tmp_path):
    blender = shutil.which("blender")
    if not blender:
        pytest.skip("optional Blender renderer unavailable")
    stage = Stage.model_validate(
        {
            "cinema": {"lighting": "sunset", "focus_distance": [6, 2], "shutter": 0.4},
            "actors": {
                "Milo": {
                    "costume": "cap",
                    "acting": [
                        {"at": 0.2},
                        {
                            "at": 0.8,
                            "blink": 1,
                            "squash": 1,
                            "gaze": 1,
                            "raise_hand": 1,
                            "smile": -1,
                            "head_turn": 1,
                        },
                    ],
                }
            },
            "orbit": {"yaw": [0, 360]},
        }
    )
    config = tmp_path / "shot.json"
    config.write_text(
        json.dumps(
            {
                "stage": stage.to_json_obj(),
                "camera": Camera().to_json_obj(),
                "cues": {"Milo": [[0, 0, 0]] * 24 + [[1, 0, 0]]},
                "frames": 25,
                "height": 1080,
            }
        )
    )
    # Evaluate real Blender properties and their animation curves, including shape keys.
    code = """
import sys
from pathlib import Path
import json
import bpy
from math import cos, isclose, prod, radians, sin
from blender_stage import build_scene
sc = build_scene(Path(sys.argv[-1]))
objs = bpy.data.objects
cam = sc.camera
assert sc.render.engine == 'CYCLES' and sc.cycles.device == 'CPU'
assert sc.render.use_motion_blur and isclose(sc.render.motion_blur_shutter, .4, abs_tol=1e-5)
assert (sc.render.resolution_x, sc.render.resolution_y) == (1920, 1080)
assert cam.data.dof.use_dof and objs['AL Rim'].data.energy > 0
skin = objs['Milo.face'].active_material.node_tree.nodes['Principled BSDF']
cloth = objs['Milo.body'].active_material.node_tree.nodes['Principled BSDF']
assert skin.inputs['Subsurface Weight'].default_value > 0
assert cloth.inputs['Normal'].is_linked and cloth.inputs['Sheen Weight'].default_value > 0
mouth = objs['Milo.mouth'].data.shape_keys.key_blocks['AL_open']
for frame, focus, turn, opening in [(1,6,0,0),(13,4,.48,0),(25,2,.96,1)]:
    sc.frame_set(frame)
    assert isclose(cam.data.dof.focus_distance, focus, abs_tol=1e-5)
    assert isclose(objs['Milo.head'].rotation_euler.z, turn, abs_tol=1e-5)
    assert isclose(prod(objs['Milo'].scale), 1, abs_tol=1e-5)
    assert isclose(mouth.value, opening, abs_tol=1e-5)
assert objs['Milo.mouth'].data.shape_keys.key_blocks['AL_smile'].value == -1
assert objs['Eye socket'].scale.z < .05 and objs['Eye aim'].location.x > .03
assert objs['Shoulder.001'].rotation_euler.y < -2
sc.frame_set(7)
# At 25% of the shot a smoothstep orbit has traversed 56.25 degrees.
assert isclose(cam.location.x, 4.8 * sin(radians(56.25)) * cos(radians(6)),
               abs_tol=1e-4)
# Replay the job format saved before cinematic stages and HD were added.
config = Path(sys.argv[-1])
job = json.loads(config.read_text())
del job['height'], job['stage']['cinema']
config.write_text(json.dumps(job))
preview = build_scene(config)
assert preview.render.engine == 'BLENDER_WORKBENCH'
assert (preview.render.resolution_x, preview.render.resolution_y) == (640, 360)
"""
    worker = EXAMPLE.parents[1] / "src" / "animalite"
    check = tmp_path / "evaluate.py"
    check.write_text("import sys\nsys.path.insert(0, " + repr(str(worker)) + ")\n" + code)
    result = run_capture(
        [
            blender,
            "-b",
            "-t",
            "2",
            "--python-exit-code",
            "1",
            "--python",
            str(check),
            "--",
            str(config),
        ],
        timeout=90,
    )
    assert result.returncode == 0, (result.stdout + result.stderr).decode(errors="replace")[-2500:]


@pytest.mark.slow
@pytest.mark.media
def test_cinematic_story_renders_visible_motion(tmp_path, tools):
    if not shutil.which("blender"):
        pytest.skip("optional Blender renderer unavailable")
    shot = {
        "action": "turn",
        "seconds": 1,
        "stage": {
            "actors": {"Milo": {"acting": [{"at": 0}, {"at": 1, "raise_hand": 1, "head_turn": 1}]}},
            "cinema": {"samples": 1},
            "orbit": {"yaw": [-12, 18]},
        },
    }
    board = tmp_path / "input.json"
    board.write_text(json.dumps({"story": "A silent gesture", "shots": [shot]}))
    path = render_story(
        board, tmp_path / "runs", "classical-warp-baseline", AdmissionPurpose.PRODUCTION
    )
    frames = gray_frames(tools.ffmpeg_path, path)
    assert frames.shape == (24, 360, 640)
    assert np.percentile(frames[0], 95) - np.percentile(frames[0], 5) > 30
    assert np.abs(frames[-1].astype(float) - frames[0]).mean() > 2
    saved = Storyboard.model_validate_json((path.parent / "storyboard.json").read_bytes())
    assert saved == Storyboard.model_validate_json(board.read_bytes())


@pytest.mark.slow
@pytest.mark.media
def test_cinema_preserves_imported_material_and_native_hd(tmp_path, tools):
    if not shutil.which("blender"):
        pytest.skip("optional Blender renderer unavailable")
    # A green triangle on the glTF XY plane faces the camera after Y-up conversion.
    positions = struct.pack("<9f", -1, 0, 0, 1, 0, 0, 0, 2, 0)
    material = {
        "pbrMetallicRoughness": {"baseColorFactor": [0.01, 0.8, 0.02, 1], "metallicFactor": 0},
        "doubleSided": True,
    }
    asset = {
        "asset": {"version": "2.0"},
        "scenes": [{"nodes": [0]}],
        "scene": 0,
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "material": 0}]}],
        "materials": [material],
        "buffers": [{"byteLength": len(positions)}],
        "bufferViews": [{"buffer": 0, "byteLength": len(positions)}],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": 3,
                "type": "VEC3",
                "min": [-1, 0, 0],
                "max": [1, 2, 0],
            }
        ],
    }
    meta = json.dumps(asset).encode()
    meta += b" " * (-len(meta) % 4)
    chunks = (
        struct.pack("<I4s", len(meta), b"JSON")
        + meta
        + struct.pack("<I4s", len(positions), b"BIN\0")
        + positions
    )
    (tmp_path / "triangle.glb").write_bytes(
        struct.pack("<4sII", b"glTF", 2, len(chunks) + 12) + chunks
    )
    board = tmp_path / "board.json"
    board.write_text(
        json.dumps(
            {
                "story": "Green triangle",
                "height": 720,
                "shots": [
                    {
                        "action": "hold",
                        "seconds": 1,
                        "stage": {
                            "model": "triangle.glb",
                            "cinema": {
                                "set": "asset",
                                "lighting": "sunset",
                                "samples": 1,
                                "denoise": False,
                            },
                        },
                    }
                ],
            }
        )
    )
    movie = render_story(
        board, tmp_path / "runs", "classical-warp-baseline", AdmissionPurpose.PRODUCTION
    )
    probe = probe_output(tools, movie)
    assert (probe.width, probe.height, probe.counted_frames) == (1280, 720, 24)
    crop = run_capture(
        [
            tools.ffmpeg_path,
            "-v",
            "error",
            "-i",
            str(movie),
            "-vf",
            "crop=32:32:(iw-32)/2:(ih-32)/2",
            "-frames:v",
            "1",
            "-pix_fmt",
            "rgb24",
            "-threads",
            "1",
            "-f",
            "rawvideo",
            "-",
        ],
        timeout=30,
    )
    assert crop.returncode == 0
    red, green, blue = np.frombuffer(crop.stdout, dtype=np.uint8).reshape(-1, 3).mean(axis=0)
    assert green > red + 40 and green > blue + 40
