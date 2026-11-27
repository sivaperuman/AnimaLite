"""Blender-only worker. Invoked in an isolated process with one JSON job."""

# mypy: allow-untyped-defs, allow-untyped-calls
from __future__ import annotations

import importlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import bpy  # type: ignore[import-not-found]
from mathutils import Euler, Vector  # type: ignore[import-not-found]


def color(value):
    def linear(byte):
        s = int(byte, 16) / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

    return (*(linear(value[i : i + 2]) for i in (1, 3, 5)), 1.0)


def oval(name, position, scale, tone):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, location=position)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    material = bpy.data.materials.get(tone) or bpy.data.materials.new(tone)
    material.diffuse_color = color(tone)
    obj.data.materials.append(material)
    for face in obj.data.polygons:
        face.use_smooth = True
    return obj


def limb(a, b, width, tone):
    direction = Vector(b) - Vector(a)
    obj = oval(
        "Limb", (Vector(a) + Vector(b)) / 2, (width, width, direction.length / 2 + width / 2), tone
    )
    obj.rotation_euler = direction.to_track_quat("Z", "Y").to_euler()


def actor(name, spec):
    """A three-dimensional stick figure; front is -Y and ground is Z=0."""
    x, y = spec["x"], spec["y"]
    ink = "#242D3B"
    oval("Head", (x, y, 1.76), (0.35, 0.31, 0.36), spec["skin"])
    oval("Shirt", (x, y, 1.13), (0.23, 0.175, 0.35), spec["shirt"])
    for sign in (-1, 1):
        limb((x + sign * 0.14, y, 0.92), (x + sign * 0.17, y, 0.21), 0.054, ink)
        oval("Shoe", (x + sign * 0.17, y - 0.045, 0.13), (0.103, 0.15, 0.066), ink)
        limb((x + sign * 0.19, y, 1.35), (x + sign * 0.32, y + 0.01, 1.05), 0.044, ink)
        limb((x + sign * 0.32, y + 0.01, 1.05), (x + sign * 0.36, y - 0.08, 0.85), 0.044, ink)
        oval("Hand", (x + sign * 0.36, y - 0.08, 0.83), (0.070, 0.061, 0.079), spec["skin"])
        oval("Eye", (x + sign * 0.106, y - 0.276, 1.81), (0.082, 0.045, 0.102), "#FFFBEE")
        oval("Pupil", (x + sign * 0.106 + 0.009, y - 0.316, 1.81), (0.033, 0.014, 0.047), ink)
        limb((x + sign * 0.055, y - 0.237, 1.96), (x + sign * 0.151, y - 0.226, 1.966), 0.016, ink)
    oval("Nose", (x, y - 0.315, 1.733), (0.040, 0.050, 0.035), spec["skin"])
    mouth = oval(f"{name}.mouth", (x, y - 0.292, 1.631), (0.096, 0.024, 0.015), ink)
    add_mouth_keys(mouth)
    return mouth


def add_mouth_keys(mouth):
    mouth.shape_key_add(name="Basis")
    for key, sx, sz in [("AL_open", 1, 4.4), ("AL_round", 0.60, 1.4), ("AL_wide", 1.35, 1)]:
        shape = mouth.shape_key_add(name=key)
        for vert in shape.data:
            vert.co.x *= sx
            vert.co.z *= sz


def build_scene(config):
    job = json.loads(config.read_text())
    stage, framing, frames = job["stage"], job["camera"], job["frames"]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = 24
    cinema = stage.get("cinema")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    film = importlib.import_module("blender_cinema") if cinema else None
    mouths = {}
    if stage["model"]:
        bpy.ops.import_scene.gltf(filepath=str((config.parent.parent / stage["model"]).resolve()))
        for speaker, name in stage["bindings"].items():
            obj = bpy.data.objects.get(name)
            if obj is None or obj.type != "MESH":
                raise ValueError(f"missing mouth mesh {name!r} for {speaker}")
            mouths[speaker] = obj
    elif film is not None:
        blocking = bool(
            stage.get("props")
            or stage.get("contacts")
            or any(
                a.get("motion") is not None or a.get("size", 1) != 1 or a.get("limb_scale", 1) != 1
                for a in stage["actors"].values()
            )
        )
        rigs: dict[str, Any] | None = {} if blocking else None
        for speaker, spec in stage["actors"].items():
            mouths[speaker] = film.sculpt(speaker, spec, frames, color, add_mouth_keys, rigs)
        if rigs is not None:
            importlib.import_module("blender_blocking").bake(
                scene, stage, rigs, frames, film, color
            )
    else:
        for speaker, spec in stage["actors"].items():
            mouths[speaker] = actor(speaker, spec)
        # A marked plinth gives a visible spatial reference throughout the orbit.
        xs = [a["x"] for a in stage["actors"].values()]
        ys = [a["y"] for a in stage["actors"].values()]
        cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
        rx, ry = (max(xs) - min(xs)) / 2 + 1.1, (max(ys) - min(ys)) / 2 + 1.05
        oval("Plinth", (cx, cy, -0.14), (rx, ry, 0.20), "#5C9E98")
        for i in range(12):
            a = 2 * math.pi * i / 12
            oval(
                "Marker",
                (cx + 0.88 * rx * math.cos(a), cy + 0.88 * ry * math.sin(a), -0.017),
                (0.055, 0.055, 0.018),
                "#F7D68B",
            )
    for speaker, obj in mouths.items():
        keys = obj.data.shape_keys
        for idx, key in enumerate(("AL_open", "AL_round", "AL_wide")):
            if not keys or key not in keys.key_blocks:
                raise ValueError(f"{speaker}: missing {key} shape key in mesh {obj.name}")
            morph = keys.key_blocks[key]
            for frame, weights in enumerate(job["cues"].get(speaker, [[0, 0, 0]] * frames), 1):
                morph.value = weights[idx]
                morph.keyframe_insert(data_path="value", frame=frame)
    bpy.ops.object.camera_add()
    cam = bpy.context.object
    scene.camera = cam
    scene.frame_start = 1
    scene.frame_end = frames
    orbit = stage["orbit"]
    target = Vector(orbit["target"])
    if film is not None:
        film.build_set(cinema["set"], target, color)
        film.light_scene(scene, cam, cinema, target, color)
    for i in range(frames):
        t = i / (frames - 1)
        if cinema and cinema["ease_camera"]:
            t = t * t * (3 - 2 * t)
        if cinema and cinema["focus_distance"]:
            near, far = cinema["focus_distance"]
            cam.data.dof.focus_distance = near + (far - near) * t
            cam.data.dof.keyframe_insert(data_path="focus_distance", frame=i + 1)
        yaw, pitch, roll = [
            math.radians(a + (b - a) * t) for a, b in (orbit["yaw"], orbit["pitch"], orbit["roll"])
        ]
        cam.location = target + orbit["radius"] * Vector(
            (math.sin(yaw) * math.cos(pitch), -math.cos(yaw) * math.cos(pitch), math.sin(pitch))
        )
        cam.rotation_euler = (
            (target - cam.location).to_track_quat("-Z", "Y") @ Euler((0, 0, roll)).to_quaternion()
        ).to_euler("XYZ", cam.rotation_euler)
        cam.data.lens = 42 * (
            framing["zoom_start"] + (framing["zoom_end"] - framing["zoom_start"]) * t
        )
        cam.keyframe_insert(data_path="location", frame=i + 1)
        cam.keyframe_insert(data_path="rotation_euler", frame=i + 1)
        cam.data.keyframe_insert(data_path="lens", frame=i + 1)
    if not cinema:
        scene.render.engine = "BLENDER_WORKBENCH"
        shading = scene.display.shading
        shading.color_type = "MATERIAL"
        shading.light = "STUDIO"
        shading.show_shadows = True
        shading.show_object_outline = True
        shading.object_outline_color = (0.025, 0.035, 0.045)
        shading.background_type = "WORLD"
        scene.world = bpy.data.worlds.new("Stage background")
        scene.world.color = color("#E7DABF")[:3]
        scene.view_settings.view_transform = "Standard"
        scene.display.render_aa = "FXAA"
    height = job.get("height", 360)
    scene.render.resolution_x = job.get("width", height * 16 // 9)
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(config.parent / "frame-")
    return scene


def main():
    config = Path(sys.argv[sys.argv.index("--") + 1])
    scene = build_scene(config)
    if scene.render.engine == "CYCLES" and not scene.cycles.use_denoising:
        (config.parent / "no-native-denoise").touch()
    bpy.ops.render.render(animation=True)


if __name__ == "__main__":
    main()
