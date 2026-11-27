"""Bake two-link IK, moving targets and single-owner prop contacts inside Blender."""

# mypy: allow-untyped-defs, allow-untyped-calls
from __future__ import annotations

import math
from typing import Any

import bpy  # type: ignore[import-not-found]
from mathutils import Euler, Vector  # type: ignore[import-not-found]

SIDES = (("right", -1), ("left", 1))
ZERO = Vector((0, 0, 0))


def make_rig(name, spec, root, head, eyes, shoulders, parts, pivot, part):
    size = spec.get("size", 1)
    base = pivot(name + ".base", root.location.copy())
    base.scale = (size,) * 3
    root.parent = base
    root.location = ZERO
    spine = pivot(name + ".spine", (0, 0, 0.78), root)
    for obj in [head, *shoulders, *parts["body"], *parts["suspender"], *parts["button"]]:
        obj.parent = spine
        obj.location.z -= 0.78
    rig = {
        "size": size,
        "limb_scale": spec.get("limb_scale", 1),
        "base": base,
        "pelvis": root,
        "spine": spine,
        "head": head,
        "eyes": eyes,
        "motion": spec.get("motion") or {},
    }
    for i, (hand, sign) in enumerate(SIDES):
        shoulders[i].name = name + "." + hand + ".shoulder"
        eyes[i].name = name + "." + hand + ".eye_aim"
        hip = pivot(name + "." + hand + ".hip", (sign * 0.14, 0, 0.78), root)
        ankle = pivot(name + "." + hand + ".ankle", ZERO)
        wrist = pivot(name + "." + hand + ".wrist", ZERO)
        for joint in (ankle, wrist):
            joint.scale = (size,) * 3
        for label, joint, local in [
            ("shoe", ankle, (0, -0.04, 0)),
            ("sole", ankle, (0, -0.04, -0.053)),
            ("mitten", wrist, (0, 0, -0.045)),
        ]:
            obj = parts[label][i]
            obj.parent = joint
            obj.location = local
        palm = parts["mitten"][i]
        palm.scale = (0.078, 0.052, 0.068)
        fingers = []
        for k in range(3):
            finger = part(
                "finger",
                (sign * (k - 1) * 0.042, -0.018, 0.007),
                (0.027, 0.029, 0.063),
                spec["skin"],
                "skin",
                wrist,
            )
            fingers.append(finger)
        part(
            "thumb",
            (-sign * 0.069, -0.025, -0.009),
            (0.030, 0.034, 0.052),
            spec["skin"],
            "skin",
            wrist,
        )
        thigh, sleeve, forearm = (parts[label][i] for label in ("leg", "sleeve", "forearm"))
        shin = part("shin", ZERO, (0.068, 0.072, 0.20), "#314957", "cloth", None)
        for obj in (thigh, shin, sleeve, forearm):
            obj.parent = None
        leg = (thigh, shin, pivot(name + "." + hand + ".knee", ZERO))
        arm = (sleeve, forearm, pivot(name + "." + hand + ".elbow", ZERO))
        part("knee cap", ZERO, (0.066 * size,) * 3, "#314957", "cloth", leg[2])
        part("elbow", ZERO, (0.059 * size,) * 3, spec["skin"], "skin", arm[2])
        rig[hand] = {
            "hip": hip,
            "ankle": ankle,
            "leg": leg,
            "shoulder": shoulders[i],
            "wrist": wrist,
            "arm": arm,
            "fingers": fingers,
        }
    return rig


def make_prop(name, spec, film, rgba):
    root = film.pivot("Prop." + name, spec["position"])
    root.scale = (spec["size"],) * 3

    def oval(label, pos, scale, tone, finish):
        return film.ellipsoid(
            name + "." + label, pos, scale, film.material(tone, finish, rgba), root
        )

    color = spec["color"]
    kind = spec["kind"]
    if kind == "biscuit":
        oval("biscuit", (0, 0, 0), (0.155, 0.045, 0.146), color, "wood")
        for x, z in [
            (-0.061, 0.051),
            (0.052, 0.064),
            (0.009, -0.025),
            (-0.073, -0.056),
            (0.073, -0.057),
        ]:
            oval("chip", (x, -0.039, z), (0.021, 0.009, 0.018), "#532C1E", "wood")
    elif kind == "tin":
        # A hollow, open tin: rings and a recessed bottom leave the contents visible.
        for i in range(9):
            bpy.ops.mesh.primitive_torus_add(
                major_segments=48, minor_segments=10, major_radius=0.199, minor_radius=0.014
            )
            band = bpy.context.object
            band.name = name + ".band"
            band.parent = root
            band.location = (0, 0, -0.075 + i * 0.019)
            tone = "#F7C982" if i in (0, 8) else color
            band.data.materials.append(film.material(tone, "metal", rgba))
            for face in band.data.polygons:
                face.use_smooth = True
        oval("bottom", (0, 0, -0.077), (0.202, 0.202, 0.014), color, "metal")
    elif kind == "box":
        box = film.rounded_box(
            name + ".box", (0, 0, 0), (0.28, 0.26, 0.23), film.material(color, "wood", rgba)
        )
        box.parent = root
    else:
        oval("ball", (0, 0, 0), (0.14,) * 3, color, "ceramic")
    return root


def factor(beat, frame):
    if beat["end"] == beat["frame"]:
        return 1
    u = min(1, max(0, (frame - beat["frame"]) / (beat["end"] - beat["frame"])))
    return u * u * (3 - 2 * u) if beat["ease"] == "smooth" else u


def offset_at(track, frame, field, default):
    before = default
    for beat in track:
        if beat.get(field) is None:
            continue
        if frame < beat["frame"]:
            break
        after = Vector(beat[field]) if isinstance(default, Vector) else beat[field]
        if frame <= beat["end"]:
            return before + (after - before) * factor(beat, frame)
        before = after
    return before


def position(obj, value, frame):
    obj.location = value
    obj.keyframe_insert(data_path="location", frame=frame)


def solve_links(parts, start, end, length, pole, width, frame):
    delta = end - start
    distance = delta.length
    if distance > 2 * length + 0.0001:
        raise ValueError(
            f"frame {frame}: unreachable {parts[2].name} target ({distance:.3f} > {2 * length:.3f})"
        )
    axis = delta.normalized() if distance > 1e-7 else Vector((0, 0, 1))
    bend = pole - axis * axis.dot(pole)
    if bend.length < 1e-6:
        bend = axis.orthogonal()
    middle = (start + end) * 0.5 + bend.normalized() * math.sqrt(
        max(0, length**2 - (distance * 0.5) ** 2)
    )
    position(parts[2], middle, frame)
    for obj, a, b, r in [(parts[0], start, middle, width), (parts[1], middle, end, width * 0.83)]:
        position(obj, (a + b) * 0.5, frame)
        obj.scale = (r, r, length * 0.52)
        obj.rotation_mode = "QUATERNION"
        q = (b - a).to_track_quat("Z", "Y")
        q.make_compatible(obj.rotation_quaternion)
        obj.rotation_quaternion = q
        obj.keyframe_insert(data_path="rotation_quaternion", frame=frame)


def rotation(degrees):
    return Euler(tuple(math.radians(a) for a in degrees)).to_quaternion()


def orient(obj, quaternion, frame):
    obj.rotation_mode = "QUATERNION"
    q = quaternion.copy()
    q.make_compatible(obj.rotation_quaternion)
    obj.rotation_quaternion = q
    obj.keyframe_insert(data_path="rotation_quaternion", frame=frame)


def world(obj):
    return obj.matrix_world.translation.copy()


class Blocking:
    def __init__(self, stage, rigs):
        self.rigs = rigs
        self.props = stage.get("props", {})
        self.prop_pos = {n: Vector(p["position"]) for n, p in self.props.items()}
        self.owners = {}
        self.free_rot = {n: rotation(p["rotation"]) for n, p in self.props.items()}
        self.relative_rot = {}
        self.hand_rot = {}
        self.active = {}
        self.last = {}
        self.shoulders = {}
        self.starts: dict[int, list[Any]] = {}
        for name, rig in rigs.items():
            for channel in ("left_hand", "right_hand", "eyes", "head"):
                for beat in rig["motion"].get(channel, []):
                    self.starts.setdefault(beat["frame"], []).append(((name, channel), beat))

    def prop_rotation(self, prop):
        owner = self.owners.get(prop)
        if owner is None:
            return self.free_rot[prop]
        return self.hand_rot[owner[0]] @ self.relative_rot[prop]

    def grip(self, prop, grip):
        spec = self.props[prop]
        return self.prop_rotation(prop) @ (
            Vector(spec["grips"].get(grip, (0, 0, 0))) * spec["size"]
        )

    def begin(self, frame):
        self.frame = frame
        self.cache = {}
        for name, rig in self.rigs.items():
            for hand, sign in SIDES:
                shoulder = rig[hand]["shoulder"]
                key = (name, hand + "_hand")
                track = rig["motion"].get(key[1], [])
                self.hand_rot[key] = rotation(offset_at(track, frame, "rotation", ZERO))
                # Legacy raised-hand acting remains the idle pose until an explicit reach.
                self.shoulders[key] = shoulder.matrix_world @ Vector(
                    (sign * 0.075, -0.045, -0.48 * rig["limb_scale"])
                )
                self.last.setdefault(key, self.shoulders[key])
        for key, beat in self.starts.get(frame, []):
            origin = self.last.get(key)
            if origin is None:
                head = self.rigs[key[0]]["head"]
                origin = head.matrix_world @ Vector((0, -3, 0.23))
            self.active[key] = (origin.copy(), beat)

    def destination(self, key, target, visiting):
        if target["point"] is not None:
            p = Vector(target["point"])
        elif target["local"] is not None:
            p = self.rigs[key[0]]["base"].matrix_world @ Vector(target["local"])
        elif target["actor"] is not None:
            head = self.rigs[target["actor"]]["head"]
            # Anchor at the head pivot; avoid a feedback loop when two actors look at one another.
            p = world(head) + Vector((0, 0, 0.18 * self.rigs[target["actor"]]["size"]))
        else:
            prop = target["prop"]
            p = self.prop_origin(prop, visiting) + self.grip(prop, target["grip"])
        return p + Vector(target["offset"])

    def prop_origin(self, prop, visiting):
        owner = self.owners.get(prop)
        if owner is None:
            return self.prop_pos[prop]
        key, grip = owner
        return self.resolve(key, visiting) - self.grip(prop, grip)

    def resolve(self, key, visiting):
        if key in self.cache:
            return self.cache[key]
        if key in visiting:
            raise ValueError(f"frame {self.frame}: cyclic hand/prop target involving {key}")
        if key not in self.active:
            return self.shoulders[key]
        origin, beat = self.active[key]
        if beat is None:
            value = self.rigs[key[0]]["base"].matrix_world @ origin
        else:
            end = self.destination(key, beat["target"], visiting | {key})
            value = origin.lerp(end, factor(beat, self.frame))
        self.cache[key] = value
        return value

    def contacts(self, events):
        for event in events:
            prop = event["prop"]
            key = (event["actor"], event["hand"] + "_hand")
            old = self.prop_origin(prop, set()).copy()
            old_rot = self.prop_rotation(prop).copy()
            if event["action"] == "release":
                self.free_rot[prop] = old_rot
                del self.owners[prop]
                self.prop_pos[prop] = old
                continue
            at = self.resolve(key, set())
            error = (at - old - self.grip(prop, event["grip"])).length
            if error > 0.002:
                raise ValueError(
                    f"frame {self.frame}: {key} misses {prop}.{event['grip']} by {error:.3f} units"
                )
            self.relative_rot[prop] = self.hand_rot[key].inverted() @ old_rot
            self.owners[prop] = (key, event["grip"])
            # A reaching hand becomes a carry anchor at contact. Subsequent beats move it.
            self.active[key] = (self.rigs[key[0]]["base"].matrix_world.inverted() @ at, None)
            self.cache.clear()


def bake(scene, stage, rigs, frames, film, rgba):
    props = {n: make_prop(n, p, film, rgba) for n, p in stage.get("props", {}).items()}
    block = Blocking(stage, rigs)
    events: dict[int, list[Any]] = {}
    for event in stage.get("contacts", []):
        events.setdefault(event["frame"], []).append(event)
    for frame in range(1, frames + 1):
        scene.frame_set(frame)
        for rig in rigs.values():
            body = rig["motion"].get("body", [])
            position(rig["pelvis"], offset_at(body, frame, "offset", ZERO), frame)
            rig["spine"].rotation_euler = (
                0,
                math.radians(offset_at(body, frame, "lean", 0)),
                math.radians(offset_at(body, frame, "turn", 0)),
            )
            rig["spine"].keyframe_insert(data_path="rotation_euler", frame=frame)
        bpy.context.view_layer.update()
        block.begin(frame)
        block.contacts(events.get(frame, []))
        for prop, obj in props.items():
            position(obj, block.prop_origin(prop, set()), frame)
            orient(obj, block.prop_rotation(prop), frame)
        for name, rig in rigs.items():
            for hand, sign in SIDES:
                limb = rig[hand]
                size = rig["size"]
                foot = Vector((sign * 0.15, -0.025, 0.092)) + offset_at(
                    rig["motion"].get(hand + "_foot", []), frame, "offset", ZERO
                )
                foot = rig["base"].matrix_world @ foot
                foot.z += 0.005 - rig["base"].location.z
                position(limb["ankle"], foot, frame)
                solve_links(
                    limb["leg"],
                    world(limb["hip"]),
                    foot,
                    size * max(0.37, 0.40 * (0.5 + 0.5 * rig["limb_scale"])),
                    Vector((0, -1, 0)),
                    0.079 * size,
                    frame,
                )
                key = (name, hand + "_hand")
                wrist = block.resolve(key, set())
                block.last[key] = wrist.copy()
                position(limb["wrist"], wrist, frame)
                orient(limb["wrist"], block.hand_rot[key], frame)
                solve_links(
                    limb["arm"],
                    world(limb["shoulder"]),
                    wrist,
                    0.365 * size * rig["limb_scale"],
                    Vector((sign * 0.35, 0.65, -1)),
                    0.085 * size,
                    frame,
                )
                closed = any(owner[0] == key for owner in block.owners.values())
                for finger in limb["fingers"]:
                    finger.rotation_euler.x = -0.95 if closed else 0.10
                    finger.keyframe_insert(data_path="rotation_euler", frame=frame)
            key = (name, "head")
            if key in block.active:
                point = block.resolve(key, set())
                block.last[key] = point.copy()
                head = rig["head"]
                d = head.parent.matrix_world.inverted() @ point - head.location
                head.rotation_euler.z = max(-0.84, min(0.84, math.atan2(d.x, -d.y)))
                head.rotation_euler.x = -max(
                    -0.38, min(0.38, math.atan2(d.z, math.hypot(d.x, d.y)))
                )
            rig["head"].keyframe_insert(data_path="rotation_euler", frame=frame)
        bpy.context.view_layer.update()
        for name, rig in rigs.items():
            key = (name, "eyes")
            if key in block.active:
                point = block.resolve(key, set())
                block.last[key] = point.copy()
                for eye in rig["eyes"]:
                    # Measure in head space so a blink cannot invert the vertical gaze.
                    d = rig["head"].matrix_world.inverted() @ point - eye.parent.location
                    d.normalize()
                    eye.location.x, eye.location.z = 0.045 * d.x, 0.046 * d.z
            for eye in rig["eyes"]:
                eye.keyframe_insert(data_path="location", frame=frame)
    scene.frame_set(1)
