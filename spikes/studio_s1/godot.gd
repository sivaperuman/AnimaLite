# S1 adapter. CPU image rasterization also works with Godot's dummy display.
extends SceneTree

func _initialize() -> void:
    call_deferred("run")


func bone(parent: Node2D, offset: Vector2, length_px: float) -> Bone2D:
    var result := Bone2D.new()
    result.set_autocalculate_length_and_angle(false)
    result.set_length(length_px)
    result.set_bone_angle(0)
    result.position = offset
    result.rest = result.transform
    parent.add_child(result)
    return result


func solve(folder: String) -> int:
    var input = JSON.parse_string(FileAccess.get_file_as_string(folder.path_join("targets.json")))
    if not input is Array or input.size() != 288:
        return ERR_INVALID_DATA
    var skeleton := Skeleton2D.new()
    root.add_child(skeleton)
    var upper := bone(skeleton, Vector2.ZERO, 1)
    var lower := bone(upper, Vector2.RIGHT, 1)
    var target := Node2D.new()
    skeleton.add_child(target)
    var stack := SkeletonModificationStack2D.new()
    var ik := SkeletonModification2DTwoBoneIK.new()
    stack.add_modification(ik)
    skeleton.set_modification_stack(stack)
    ik.set_joint_one_bone_idx(upper.get_index_in_skeleton())
    ik.set_joint_two_bone_idx(lower.get_index_in_skeleton())
    ik.set_target_node(skeleton.get_path_to(target))
    stack.enabled = true
    var poses := []
    for frame in input:
        var joints := []
        for c in frame:
            skeleton.position = Vector2(c[0], c[1])
            upper.set_length(c[4])
            lower.position = Vector2(c[4], 0)
            lower.set_length(c[5])
            ik.set_flip_bend_direction(c[6] > 0)
            target.global_position = Vector2(c[2], c[3])
            skeleton.execute_modifications(1.0 / 24, 0)
            var joint := lower.global_position
            var tip := lower.to_global(Vector2(c[5], 0))
            if tip.distance_to(target.global_position) > 0.002:
                push_error("Unreachable target in frame %s" % poses.size())
                return ERR_INVALID_DATA
            joints.append([joint.x, joint.y, tip.x, tip.y])
        poses.append(joints)
    var file := FileAccess.open(folder.path_join("joints.json"), FileAccess.WRITE)
    if not file:
        return FileAccess.get_open_error()
    file.store_string(JSON.stringify(poses, "", true, true))
    return OK


func raster(folder: String) -> int:
    var img := Image.new()
    for frame in range(288):
        var base := folder.path_join("%03d" % frame)
        var result := img.load_svg_from_string(FileAccess.get_file_as_string(base + ".svg"))
        if result != OK:
            return result
        result = img.save_png(base + ".png")
        if result != OK:
            return result
    return OK


func run() -> void:
    var args := OS.get_cmdline_user_args()
    if args.size() != 2:
        quit(ERR_INVALID_PARAMETER)
        return
    match args[0]:
        "solve": quit(solve(args[1]))
        "raster": quit(raster(args[1]))
        _: quit(ERR_INVALID_PARAMETER)
