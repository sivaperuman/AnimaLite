"""Cinematic stage construction inside Blender's bundled Python."""

# mypy: allow-untyped-defs, allow-untyped-calls
from __future__ import annotations

import _cycles  # type: ignore[import-not-found]
import bpy  # type: ignore[import-not-found]
from mathutils import Vector  # type: ignore[import-not-found]


def material(tone, finish, rgba):
    name = f"AL-{tone}-{finish}"
    existing = bpy.data.materials.get(name)
    if existing:
        return existing
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.diffuse_color = rgba(tone)
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = mat.diffuse_color
    bsdf.inputs["Roughness"].default_value = {
        "eye": 0.19,
        "skin": 0.43,
        "metal": 0.24,
        "cloth": 0.76,
        "wood": 0.46,
        "ceramic": 0.30,
    }[finish]
    if finish == "skin":
        bsdf.inputs["Subsurface Weight"].default_value = 0.12
        bsdf.inputs["Subsurface Scale"].default_value = 0.055
    if finish == "metal":
        bsdf.inputs["Metallic"].default_value = 0.65
    if finish == "cloth":
        bsdf.inputs["Sheen Weight"].default_value = 0.28
        noise = mat.node_tree.nodes.new("ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = 145
        bump = mat.node_tree.nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = 0.12
        bump.inputs["Distance"].default_value = 0.004
        mat.node_tree.links.new(noise.outputs["Fac"], bump.inputs["Height"])
        mat.node_tree.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def pivot(name, pos, parent=None):
    obj = bpy.data.objects.new(name, None)
    bpy.context.collection.objects.link(obj)
    obj.parent = parent
    obj.location = pos
    return obj


def ellipsoid(name, pos, scale, mat, parent=None):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=20)
    obj = bpy.context.object
    obj.name = name
    obj.parent = parent
    obj.location = pos
    obj.scale = scale
    obj.data.materials.append(mat)
    for face in obj.data.polygons:
        face.use_smooth = True
    return obj


def rounded_box(name, pos, size, mat, radius=0.06):
    bpy.ops.mesh.primitive_cube_add(size=1, location=pos)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    bevel = obj.modifiers.new("Soft edges", "BEVEL")
    bevel.width = radius
    bevel.segments = 3
    obj.modifiers.new("Normals", "WEIGHTED_NORMAL")
    obj.data.materials.append(mat)
    return obj


def sculpt(name, spec, frames, rgba, add_mouth_keys):
    root = pivot(name, (spec["x"], spec["y"], 0.04))
    head = pivot(name + ".head", (0, 0, 1.52), root)

    def part(label, position, scale, tone, finish, parent):
        return ellipsoid(name + "." + label, position, scale, material(tone, finish, rgba), parent)

    skin = spec["skin"]
    cloth = spec["shirt"]
    dark = "#332D38"
    part("face", (0, 0, 0.13), (0.44, 0.36, 0.46), skin, "skin", head)
    part("body", (0, 0, 1.04), (0.30, 0.24, 0.38), cloth, "cloth", root)
    part("trousers", (0, 0, 0.78), (0.26, 0.21, 0.19), "#314957", "cloth", root)
    part("nose", (0, -0.351, 0.11), (0.089, 0.09, 0.072), skin, "skin", head)
    gaze = []
    lids = []
    brows = []
    arms = []
    for side in [-1, 1]:
        part("ear", (side * 0.423, 0, 0.15), (0.075, 0.065, 0.104), skin, "skin", head)
        part("leg", (side * 0.13, 0, 0.49), (0.077, 0.082, 0.31), "#314957", "cloth", root)
        part(
            "shoe", (side * 0.15, -0.065, 0.105), (0.129, 0.178, 0.095), "#AD664B", "ceramic", root
        )
        part("sole", (side * 0.15, -0.067, 0.060), (0.130, 0.180, 0.039), "#F3D69A", "cloth", root)
        eye = pivot("Eye socket", (side * 0.146, -0.31, 0.233), head)
        lids.append(eye)
        part("white", (0, 0, 0), (0.119, 0.070, 0.137), "#F6E9D6", "eye", eye)
        pupil = pivot("Eye aim", (0, -0.058, 0), eye)
        gaze.append(pupil)
        part("iris", (0, 0, 0), (0.068, 0.025, 0.082), "#497C74", "eye", pupil)
        part("pupil", (0, -0.021, 0), (0.043, 0.014, 0.054), dark, "eye", pupil)
        part("glint", (-0.013, -0.033, 0.027), (0.014, 0.008, 0.017), "#FFF8DD", "eye", pupil)
        brow = part(
            "brow", (side * 0.15, -0.297, 0.409), (0.098, 0.026, 0.024), dark, "cloth", head
        )
        brows.append((side, brow))
        shoulder = pivot("Shoulder", (side * 0.236, 0, 1.26), root)
        arm = part(
            "sleeve", (side * 0.034, 0, -0.09), (0.093, 0.093, 0.15), cloth, "cloth", shoulder
        )
        arm.rotation_euler.y = -side * 0.25
        part(
            "forearm", (side * 0.075, -0.014, -0.305), (0.064, 0.068, 0.153), skin, "skin", shoulder
        )
        part("mitten", (side * 0.082, -0.025, -0.44), (0.080, 0.076, 0.083), skin, "skin", shoulder)
        arms.append(shoulder)
        strap = part(
            "suspender", (side * 0.15, -0.192, 1.04), (0.030, 0.025, 0.23), "#405865", "cloth", root
        )
        strap.rotation_euler.y = side * 0.13
        part(
            "button", (side * 0.125, -0.219, 0.936), (0.032, 0.018, 0.032), "#DEA85C", "metal", root
        )
    if spec["costume"] == "cap":
        part("cap", (0, 0.012, 0.445), (0.44, 0.365, 0.19), "#3E7580", "cloth", head)
        part("bill", (0, -0.275, 0.424), (0.36, 0.23, 0.036), "#305E69", "cloth", head)
        part("cap button", (0, 0.016, 0.631), (0.048, 0.049, 0.032), "#E4A459", "cloth", head)
    else:
        for i in range(3):
            tuft = part(
                "quiff",
                (-0.15 + i * 0.115, -0.078, 0.541),
                (0.10, 0.13, 0.15 - i * 0.016),
                "#55403B",
                "cloth",
                head,
            )
            tuft.rotation_euler.y = -0.52
    mouth = part("mouth", (0, -0.327, -0.012), (0.103, 0.024, 0.014), dark, "skin", head)
    add_mouth_keys(mouth)
    # A separate relative key bends the corners while speech opens the jaw.
    smile = mouth.shape_key_add(name="AL_smile")
    smile.slider_min = -1
    for vertex in smile.data:
        vertex.co.z += 2.8 * vertex.co.x**2
    animate(spec, frames, root, head, gaze, lids, brows, arms, smile)
    return mouth


def animate(spec, frames, root, head, gaze, lids, brows, arms, smile):
    poses = spec["acting"]
    if not poses:
        return
    # Hold the first and last poses. Cubic easing arrives at deliberate accents.
    right = 0
    for i in range(frames):
        t = i / (frames - 1)
        while right < len(poses) - 1 and t > poses[right]["at"]:
            right += 1
        a, b = poses[max(0, right - 1)], poses[right]
        span = b["at"] - a["at"]
        u = min(1, max(0, (t - a["at"]) / span)) if span else 0
        u = u * u * (3 - 2 * u)

        def value(key, a=a, b=b, u=u):
            start = a.get(key, 0)
            return start + (b.get(key, 0) - start) * u

        head.rotation_euler = (0, value("head_tilt") * 0.42, value("head_turn") * 0.96)
        head.keyframe_insert(data_path="rotation_euler", frame=i + 1)
        smile.value = value("smile")
        smile.keyframe_insert(data_path="value", frame=i + 1)
        squash = value("squash")
        height = 1 - 0.13 * squash
        root.scale = (height**-0.5, height**-0.5, height)
        root.keyframe_insert(data_path="scale", frame=i + 1)
        for eye, lid, (side, brow) in zip(gaze, lids, brows, strict=True):
            eye.location.x = value("gaze") * 0.039
            eye.keyframe_insert(data_path="location", frame=i + 1)
            lid.scale.z = 1 - 0.965 * value("blink")
            lid.keyframe_insert(data_path="scale", frame=i + 1)
            brow.location.z = 0.409 + 0.047 * value("brow")
            brow.rotation_euler.y = side * (0.12 + 0.35 * value("brow"))
            brow.keyframe_insert(data_path="location", frame=i + 1)
            brow.keyframe_insert(data_path="rotation_euler", frame=i + 1)
        arms[1].rotation_euler = (value("raise_hand") * -0.36, value("raise_hand") * -2.45, 0)
        arms[1].keyframe_insert(data_path="rotation_euler", frame=i + 1)


def build_set(preset, target, rgba):
    if preset == "asset":
        return
    x, y, _ = target

    def box(label, pos, sz, tone, finish):
        return rounded_box(
            label, (x + pos[0], y + pos[1], pos[2]), sz, material(tone, finish, rgba)
        )

    box(
        "Floor",
        (0, 0, -0.13),
        (60, 60, 0.27),
        "#8CAEA5" if preset == "studio" else "#AD7959",
        "wood",
    )
    if preset == "studio":
        return
    box("Workshop plaster", (0, 4.1, 3), (18, 0.22, 6.5), "#517572", "cloth")
    for shelf in [1.05, 2.35]:
        box("Maple shelf", (0, 3.68, shelf), (9, 0.75, 0.14), "#C99A6D", "wood")
        for i in range(16):
            px = -3.9 + 0.52 * i
            h = 0.26 + 0.19 * ((i * 7 + int(shelf)) % 5) / 4
            tone = ["#DFB15C", "#9BC3B3", "#BD7770", "#3C6368"][(i + int(shelf)) % 4]
            mat = material(tone, "ceramic", rgba)
            ellipsoid(
                "Glazed jar",
                (x + px, y + 3.61, shelf + 0.06 + h * 0.48),
                (0.15, 0.15, h * 0.52),
                mat,
            )
            box("Jar lid", (px, 3.61, shelf + 0.07 + h), (0.19, 0.19, 0.065), "#765641", "wood")


def light_scene(scene, cam, config, target, rgba):
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = config["samples"]
    scene.render.use_persistent_data = True
    scene.cycles.use_denoising = config["denoise"] and getattr(
        _cycles, "with_openimagedenoise", False
    )
    scene.cycles.max_bounces = 4
    scene.render.use_motion_blur = bool(config["shutter"])
    scene.render.motion_blur_shutter = config["shutter"]
    scene.view_settings.view_transform = "AgX"
    scene.world = bpy.data.worlds.new("Ambient studio")
    scene.world.use_nodes = True
    bg = scene.world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = rgba("#D4E3F0")
    bg.inputs["Strength"].default_value = 0.35
    sunset = config["lighting"] == "sunset"
    lamps = [
        ("Key", (-3, -3.4, 4.5), 560, 3.3, "#FFA877" if sunset else "#FFE4C7"),
        ("Fill", (3, -2.8, 2.5), 235, 3.0, "#AECDF6"),
        ("Rim", (1.6, 2.8, 3.3), 680, 2.4, "#FFD79D"),
    ]
    for label, offset, power, size, tone in lamps:
        data = bpy.data.lights.new("AL " + label, "AREA")
        data.energy = power
        data.shape = "DISK"
        data.size = size
        data.color = rgba(tone)[:3]
        obj = bpy.data.objects.new("AL " + label, data)
        scene.collection.objects.link(obj)
        obj.location = target + Vector(offset)
        obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()
    cam.data.dof.use_dof = config["focus_distance"] is not None
    cam.data.dof.aperture_fstop = config["f_stop"]
