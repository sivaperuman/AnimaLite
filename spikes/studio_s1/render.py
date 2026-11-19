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
from performance import FRAMES, pose
from PIL import Image

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


def godot_frames(folder, executable, width, deadline):
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

    poses = [pose(frame) for frame in range(FRAMES)]
    targets = [
        [chain.controls() for actor in actors[:2] for chain in actor.chains] for actors in poses
    ]
    save(frames / "targets.json", targets)
    call("solve")
    positions = json.loads((frames / "joints.json").read_text())
    for f, (actors, points) in enumerate(zip(poses, positions, strict=True)):
        pairs = [(complex(x, y), complex(tx, ty)) for x, y, tx, ty in points]
        (frames / f"{f:03}.svg").write_text(svg(f, actors, (pairs[:4], pairs[4:]), width))
    call("raster")
    for f in range(FRAMES):
        with Image.open(frames / f"{f:03}.png") as image:
            yield image.convert("RGB").tobytes()


def native_frames(width):
    from resvg_py import svg_to_bytes

    for frame in range(FRAMES):
        actors = pose(frame)
        joints = [[(c.joint(), c.tip) for c in a.chains] for a in actors[:2]]
        png = svg_to_bytes(svg_string=svg(frame, actors, joints, width), skip_system_fonts=True)
        with Image.open(io.BytesIO(png)) as image:
            yield image.convert("RGB").tobytes()


def cpu_seconds():
    usage = [resource.getrusage(who) for who in (resource.RUSAGE_SELF, resource.RUSAGE_CHILDREN)]
    return sum(r.ru_utime + r.ru_stime for r in usage)


def render(folder, backend, width):
    start = time.monotonic()
    cpu_start = cpu_seconds()
    deadline = start + 180
    output = OutputSpec(
        width=width,
        height=width * 9 // 16,
        animation_frame_count=FRAMES,
        cadence=CadencePolicy(animation_fps=24, delivery_fps=24),
    )
    tools = FFmpegTools.discover().with_content_hashes()
    tools.require()
    settings = {
        "profile": "studio-s1-" + backend,
        "schema_version": 1,
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
                "render.py",
                "godot.gd",
                "requirements.txt",
            )
        },
        "encoder_threads": 1,
        "audio": "silent visual acting study",
    }
    if backend == "godot":
        executable = shutil.which("godot")
        if not executable:
            raise RuntimeError("Godot executable unavailable")
        settings["godot_binary_sha256"] = digest(Path(executable))
        frames = godot_frames(folder, executable, width, deadline)
    else:
        settings["resvg_py"] = version("resvg-py")
        frames = native_frames(width)
    save(folder / "settings.json", settings)
    partial = folder / "partial.mp4"
    frame_hashes = []

    def observed():
        for rgb in frames:
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
    scratch = folder / "scratch"
    scratch_bytes = sum(p.stat().st_size for p in scratch.rglob("*") if p.is_file())
    record = {
        "settings_sha256": digest(folder / "settings.json"),
        "output_sha256": digest(partial),
        "probe": probe.model_dump(mode="json"),
        "rgb_sha256_by_frame": frame_hashes,
        "frames": {
            "authored_source_images": 0,
            "procedural_from_authored_controls": FRAMES,
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
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    args.workspace.mkdir(parents=True, exist_ok=True)
    attempt = Path(tempfile.mkdtemp(prefix=args.backend + "-", dir=args.workspace)).resolve()
    print(attempt, flush=True)
    try:
        render(attempt, args.backend, args.width)
    except BaseException as exc:
        save(attempt / "failure.json", {"error": type(exc).__name__, "detail": str(exc)})
        raise


if __name__ == "__main__":
    main()
