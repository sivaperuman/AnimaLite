"""Local S1 lab entry point. Run directly from a Package A development venv."""

import argparse
import hashlib
import io
import json
import os
import platform
import resource
import shutil
import sys
import tempfile
import time
from importlib.metadata import version
from pathlib import Path

from artwork import HERE, svg
from grip_review import visible_grips
from performance import FRAMES, inspector_pose, pose
from PIL import Image
from take_review import decoded_review

from animalite.contracts.media import CadencePolicy, OutputSpec
from animalite.contracts.profile import ThreadBudget
from animalite.media.encode import encode_delivery_stream
from animalite.media.ffmpeg import FFmpegTools
from animalite.media.probe import probe_output, validate_output
from animalite.proc import run_capture


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def save(path, obj):
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def godot_frames(folder, executable, width, deadline, shot, pose_at, character, gaze):
    # The fixed shot bounds scratch to 288 SVGs and PNGs. No scene reads a user script.
    frames = folder / "scratch"
    frames.mkdir()
    (frames / "project.godot").write_text(
        "config_version=5\n[threading]\nworker_pool/max_threads=1\n"
    )
    env = dict(os.environ)
    for category in ("DATA", "CONFIG", "CACHE"):
        env[f"XDG_{category}_HOME"] = str(frames)

    def call(mode):
        result = run_capture(
            [
                executable,
                "--headless",
                "--single-threaded-scene",
                "--path",
                str(frames),
                "--script",
                str(HERE / "godot.gd"),
                "--",
                mode,
                str(frames),
            ],
            timeout=deadline - time.monotonic(),
            env=env,
        )
        log = result.stdout + result.stderr
        (folder / f"godot-{mode}.log").write_bytes(log)
        if result.returncode or result.survivors or b"SCRIPT ERROR:" in log or b"ERROR:" in log:
            raise RuntimeError(f"Godot {mode} failed. See {folder}/godot-{mode}.log")

    # Godot updates bone transforms in place. Replay the cheap IK prefix so a
    # mid-shot preview has exactly the same poses as the full-shot raster.
    poses = [pose_at(frame) for frame in range(shot.stop)]
    targets = [
        [chain.controls() for actor in actors[:2] for chain in actor.chains] for actors in poses
    ]
    save(frames / "targets.json", targets)
    call("solve")
    positions = json.loads((frames / "joints.json").read_text())
    if len(positions) != len(poses):
        raise ValueError("Godot returned an incomplete solve")
    poses = poses[shot.start :]
    positions = positions[shot.start :]
    if shot.start:
        save(frames / "joints.json", positions)
    for f, (actors, points) in enumerate(zip(poses, positions, strict=True)):
        pairs = [(complex(x, y), complex(tx, ty)) for x, y, tx, ty in points]
        (frames / f"{f:03}.svg").write_text(
            svg(shot[f], actors, (pairs[:4], pairs[4:]), width, character, gaze)
        )
    call("raster")
    for f in range(len(shot)):
        with Image.open(frames / f"{f:03}.png") as image:
            yield poses[f], image.convert("RGB").tobytes()


def native_frames(width, shot, pose_at, character, gaze):
    from resvg_py import svg_to_bytes

    for frame in shot:
        actors = pose_at(frame)
        joints = [[(c.joint(), c.tip) for c in a.chains] for a in actors[:2]]
        png = svg_to_bytes(
            svg_string=svg(frame, actors, joints, width, character, gaze), skip_system_fonts=True
        )
        with Image.open(io.BytesIO(png)) as image:
            yield actors, image.convert("RGB").tobytes()


def cpu_seconds():
    usage = [resource.getrusage(who) for who in (resource.RUSAGE_SELF, resource.RUSAGE_CHILDREN)]
    return sum(r.ru_utime + r.ru_stime for r in usage)


def frame_range(first, stop):
    if not 0 <= first < stop <= FRAMES or stop - first < 2:
        raise ValueError(f"Select at least two frames within [0, {FRAMES})")
    return range(first, stop)


def render(folder, backend, width, *, first=0, stop=FRAMES, character="owner", gaze="directed"):
    shot = frame_range(first, stop)
    if character != "inspector" and gaze != "directed":
        raise ValueError("The fixed-gaze comparison needs the painted inspector")
    pose_at = inspector_pose if character == "inspector" else pose
    start = time.monotonic()
    cpu_start = cpu_seconds()
    deadline = start + 180
    output = OutputSpec(
        width=width,
        height=width * 9 // 16,
        animation_frame_count=len(shot),
        cadence=CadencePolicy(animation_fps=24, delivery_fps=24),
    )
    tools = FFmpegTools.discover().with_content_hashes()
    tools.require()
    settings = {
        "profile": "studio-s1-" + backend,
        "schema_version": 2,
        "source_frame_range": [first, stop],
        "character": character,
        "gaze": gaze,
        "output": output.model_dump(mode="json"),
        "device": "local CPU",
        "pillow": version("Pillow"),
        "python": sys.version,
        "system": platform.platform(),
        "media_tools": tools.selection().model_dump(mode="json"),
        "source_sha256": {
            name: digest(HERE / name)
            for name in (
                "site.svg",
                "rigs.json",
                "milo.svg",
                "owner.svg",
                "performance.py",
                "artwork.py",
                "grip_review.py",
                "render.py",
                "take_review.py",
                "godot.gd",
                "requirements.txt",
            )
        },
        "encoder_threads": 1,
        "audio": "silent visual acting study",
    }
    if character == "inspector":
        for name in (
            "inspector_art.py",
            "inspector/expressions.webp",
            "inspector/coat.webp",
            "inspector/boot.webp",
        ):
            settings["source_sha256"][name] = digest(HERE / name)
    if backend == "godot":
        executable = shutil.which("godot")
        if not executable:
            raise RuntimeError("Godot executable unavailable")
        settings["godot_binary_sha256"] = digest(Path(executable))
        frames = godot_frames(folder, executable, width, deadline, shot, pose_at, character, gaze)
    else:
        settings["resvg_py"] = version("resvg-py")
        frames = native_frames(width, shot, pose_at, character, gaze)
    save(folder / "settings.json", settings)
    partial = folder / "partial.mp4"
    frame_hashes = []

    grip_pixels = []

    def observed():
        for frame, (actors, rgb) in zip(shot, frames, strict=True):
            grip_pixels.append(visible_grips(rgb, width, frame, actors, character))
            frame_hashes.append(hashlib.sha256(rgb).hexdigest())
            yield rgb

    encoded = encode_delivery_stream(
        tools,
        observed(),
        output,
        partial,
        thread_budget=ThreadBudget(total_threads=2, inference_threads=0),
        timeout_seconds=deadline - time.monotonic(),
        stderr_path=folder / "ffmpeg.log",
    )
    if encoded.survivors:
        raise RuntimeError(f"Encoder cleanup failed {encoded.survivors}")
    probe = probe_output(tools, partial, timeout=deadline - time.monotonic())
    problems = validate_output(probe, output)
    if problems or probe.codec != "h264" or probe.profile != "High":
        raise RuntimeError(f"Invalid clip {probe} {problems}")
    wall = time.monotonic() - start
    cpu = cpu_seconds() - cpu_start
    review_start = time.monotonic()
    review = decoded_review(tools.ffmpeg_path, partial, shot, folder / "review.webp", deadline)
    output_hash = digest(partial)
    save(folder / "review.json", {**review, "output_sha256": output_hash})
    review_seconds = time.monotonic() - review_start
    scratch = folder / "scratch"
    scratch_bytes = sum(p.stat().st_size for p in scratch.rglob("*") if p.is_file())
    record = {
        "settings_sha256": digest(folder / "settings.json"),
        "output_sha256": output_hash,
        "decoded_review_seconds": review_seconds,
        "review_sha256": digest(folder / "review.json"),
        "review_sheet_sha256": digest(folder / "review.webp"),
        "probe": probe.model_dump(mode="json"),
        "rgb_sha256_by_frame": frame_hashes,
        "visible_grip_pixels_by_frame": grip_pixels,
        "source_frame_range": [first, stop],
        "frames": {
            "authored_source_images": int(character == "inspector"),
            "procedural_from_authored_controls": len(shot),
            "learned": 0,
            "delivery_duplicates": 0,
        },
        "qualifying": False,
        "setup_render_encode_probe_seconds": wall,
        "process_tree_cpu_seconds": cpu,
        "parent_peak_rss_KiB": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "largest_reaped_child_peak_rss_KiB": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
        "scratch_payload_bytes_before_cleanup": scratch_bytes,
        "paid_ai_video_calls": 0,
    }
    save(folder / "manifest.json", record)
    if scratch.exists():
        shutil.rmtree(scratch)
    partial.rename(folder / "marvel-engineer.mp4")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", required=True, choices=("godot", "native"))
    parser.add_argument("--width", type=int, choices=(640, 1280), default=1280)
    parser.add_argument("--character", choices=("owner", "inspector"), default="owner")
    parser.add_argument("--gaze", choices=("directed", "fixed"), default="directed")
    parser.add_argument("--start-frame", type=int, default=0)
    parser.add_argument("--stop-frame", type=int, default=FRAMES, help="Exclusive source frame")
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    args.workspace.mkdir(parents=True, exist_ok=True)
    attempt = Path(tempfile.mkdtemp(prefix=args.backend + "-", dir=args.workspace)).resolve()
    print(attempt, flush=True)
    try:
        render(
            attempt,
            args.backend,
            args.width,
            first=args.start_frame,
            stop=args.stop_frame,
            character=args.character,
            gaze=args.gaze,
        )
    except BaseException as exc:
        save(attempt / "failure.json", {"error": type(exc).__name__, "detail": str(exc)})
        raise


if __name__ == "__main__":
    main()
