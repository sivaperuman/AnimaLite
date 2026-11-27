"""Run inside Blender to check evaluated poses across a handoff and step."""

import json
import sys
from importlib import import_module
from itertools import pairwise
from pathlib import Path

import bpy  # type: ignore[import-not-found]
from mathutils import Vector  # type: ignore[import-not-found]


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "animalite"))
    build_scene = import_module("blender_stage").build_scene
    path = Path(sys.argv[-1])
    job = json.loads(path.read_bytes())
    scene = build_scene(path)
    objects = bpy.data.objects
    anchors: dict[str, Vector] = {}
    lengths: dict[str, float] = {}
    donor_curl = []
    receiver_curl = []

    def pos(name):
        return objects[name].matrix_world.translation.copy()

    def grip(prop, name):
        p = job["stage"]["props"][prop]
        return objects["Prop." + prop].matrix_world @ Vector(p["grips"][name])

    def curl(wrist):
        return next(c for c in objects[wrist].children if ".finger" in c.name).rotation_euler.x

    for frame in range(1, 145):
        scene.frame_set(frame)
        donor_curl.append(curl("Milo.left.wrist"))
        receiver_curl.append(curl("Max.right.wrist"))
        if frame == 28:
            reach_start = pos("Milo.left.wrist")
        if frame == 35:
            progress = (frame - 28) / (43 - 28)
            progress = progress**2 * (3 - 2 * progress)
            straight = reach_start.lerp(grip("Biscuit", "edge"), progress)
            expected = straight + Vector((0, 0, 4 * progress * (1 - progress) * 0.055))
            assert (pos("Milo.left.wrist") - expected).length < 1e-4
        for actor_name in ("Milo", "Max"):
            for side in ("left", "right"):
                ankle = actor_name + "." + side + ".ankle"
                assert (pos(ankle) - anchors.setdefault(ankle, pos(ankle))).length < 1e-5
                sole = next(c for c in objects[ankle].children if ".sole" in c.name)
                bottom = min((sole.matrix_world @ Vector(v)).z for v in sole.bound_box)
                assert abs(bottom - 0.005) < 1e-4, (frame, sole.name, bottom)
                for first, joint, last in [
                    ("shoulder", "elbow", "wrist"),
                    ("hip", "knee", "ankle"),
                ]:
                    prefix = actor_name + "." + side + "."
                    length = (pos(prefix + first) - pos(prefix + joint)).length
                    assert abs(length - (pos(prefix + joint) - pos(prefix + last)).length) < 1e-4
                    key = prefix + joint
                    assert abs(length - lengths.setdefault(key, length)) < 1e-4
        assert (pos("Milo.right.wrist") - grip("Tin", "rim")).length < 1e-4
        if frame <= 43:
            start = Vector(job["stage"]["props"]["Biscuit"]["position"])
            assert (pos("Prop.Biscuit") - start).length < 1e-4
        if 43 <= frame <= 91:
            assert (pos("Milo.left.wrist") - grip("Biscuit", "edge")).length < 1e-4
        if frame >= 91:
            assert (pos("Max.right.wrist") - grip("Biscuit", "other")).length < 1e-4
        if frame in (36, 43):
            eye = objects["Max.right.eye_aim"].location.x
            head = objects["Max.head"].rotation_euler.z
            if frame == 36:
                first_eye, first_head = eye, head
            else:
                assert abs(first_eye - eye) > 0.02 and abs(first_head - head) < 1e-5
        if frame == 91:
            for name, opened in [("Milo", 1), ("Max", 0)]:
                assert (
                    objects[name + ".mouth"].data.shape_keys.key_blocks["AL_open"].value == opened
                )
            transfer = pos("Prop.Biscuit")
        if frame == 92:
            assert (transfer - pos("Prop.Biscuit")).length < 1e-4
    assert abs(objects["Prop.Tin"].rotation_quaternion.angle) > 0.4
    # Frame-indexed samples include the fully open and fully closed endpoints.
    for samples, contact in [(donor_curl, 43), (receiver_curl, 91)]:
        approach = samples[contact - 5 : contact]
        assert abs(approach[0] - 0.10) < 1e-5 and abs(approach[-1] + 0.95) < 1e-5
        assert all(a > b for a, b in pairwise(approach))
    release = donor_curl[90:95]
    assert abs(release[0] + 0.95) < 1e-5 and abs(release[-1] - 0.10) < 1e-5
    assert all(a < b for a, b in pairwise(release))
    # Release a turned prop; its world transform must persist after the hand moves away.
    job["stage"]["contacts"].append(
        {
            "frame": 128,
            "action": "release",
            "actor": "Max",
            "hand": "right",
            "prop": "Biscuit",
            "grip": "other",
        }
    )
    path.write_text(json.dumps(job))
    scene = build_scene(path)
    objects = bpy.data.objects
    scene.frame_set(128)
    held = objects["Prop.Biscuit"].matrix_world.copy()
    wrist = pos("Max.right.wrist")
    assert abs(curl("Max.right.wrist") + 0.95) < 1e-5
    scene.frame_set(130)
    assert -0.95 < curl("Max.right.wrist") < 0.10
    scene.frame_set(144)
    assert abs(curl("Max.right.wrist") - 0.10) < 1e-5
    assert (wrist - pos("Max.right.wrist")).length > 0.025
    assert all(
        abs(a - b) < 1e-5
        for row_a, row_b in zip(held, objects["Prop.Biscuit"].matrix_world, strict=True)
        for a, b in zip(row_a, row_b, strict=True)
    )
    # A missed grasp, impossible reach, or circular cross-target must fail the build.
    for issue in ("miss", "reach", "cycle"):
        bad = json.loads(json.dumps(job))
        if issue == "miss":
            bad["stage"]["contacts"][1]["frame"] = 29
        elif issue == "reach":
            bad["stage"]["actors"]["Milo"]["motion"]["left_hand"][0]["target"]["local"] = [3, 3, 3]
        else:
            bad["stage"]["actors"]["Milo"]["motion"]["right_hand"][1]["target"] = {
                "point": None,
                "actor": None,
                "local": None,
                "prop": "Tin",
                "grip": "rim",
                "offset": [0, 0, 0],
            }
        path.write_text(json.dumps(bad))
        try:
            build_scene(path)
        except ValueError as error:
            assert {"miss": "misses", "reach": "unreachable", "cycle": "cyclic"}[issue] in str(
                error
            ), error
        else:
            raise AssertionError(issue)
    # Known footfall beats: one foot lifts, the supporting foot stays on the floor.
    job["frames"] = 24
    job["cues"] = {}
    job["stage"]["props"] = {}
    job["stage"]["contacts"] = []
    actor = job["stage"]["actors"]["Milo"]
    actor.update(motion=json.loads((path.parent / "step.json").read_text()), acting=[], size=0.8)
    job["stage"]["actors"] = {"Milo": actor}
    path.write_text(json.dumps(job))
    scene = build_scene(path)
    objects = bpy.data.objects
    scene.frame_set(1)
    left = pos("Milo.left.ankle")
    right = pos("Milo.right.ankle")
    scene.frame_set(8)
    assert abs(pos("Milo.left.ankle").z - left.z - 0.072) < 1e-5
    assert (right - pos("Milo.right.ankle")).length < 1e-5
    scene.frame_set(16)
    assert abs(pos("Milo.right.ankle").z - right.z - 0.072) < 1e-5
    assert abs(pos("Milo.left.ankle").z - left.z) < 1e-5
    scene.frame_set(24)
    for side, start in [("left", left), ("right", right)]:
        assert (pos("Milo." + side + ".ankle") - start - Vector((0.152, 0, 0))).length < 1e-5


if __name__ == "__main__":
    main()
