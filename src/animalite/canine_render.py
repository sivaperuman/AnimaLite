"""Render a reusable gallop and export the exact four limb tracks used by the artwork."""

from __future__ import annotations

import base64
import json
import shutil
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path

from animalite.canine import DogDesign, GallopFrame, GallopShot, View, running_frame
from animalite.canine_art import countryside, dog_art
from animalite.canine_plate import RunningLane
from animalite.contracts.base import sha256_file
from animalite.dog_walk_art import ellipse
from animalite.errors import JobTimeoutError, ValidationRejected
from animalite.proc import run_capture


def retain_image(image: Path, source_root: Path, run: Path) -> Path:
    """Retain referenced drawings once by digest, with paths relative to the replay manifest."""
    source = (source_root / image).resolve(strict=True)
    suffix = source.suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"} or not source.is_file():
        raise ValidationRejected(f"expected a PNG, JPEG or WebP drawing: {source}")
    digest = sha256_file(str(source)).removeprefix("sha256:")
    relative = Path("artwork") / (digest + suffix)
    dest = run / relative
    dest.parent.mkdir(exist_ok=True)
    if not dest.exists():
        shutil.copyfile(source, dest)
    return relative


def retain_design(dog: DogDesign, source_root: Path, run: Path) -> DogDesign:
    drawings = {
        look: {
            view: art.model_copy(update={"image": retain_image(art.image, source_root, run)})
            for view, art in views.items()
        }
        for look, views in dog.head_drawings.items()
    }
    return dog.model_copy(update={"head_drawings": drawings})


def _uri(file: Path) -> str:
    kind = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".webp": "webp"}[file.suffix.lower()]
    return f"data:image/{kind};base64," + base64.b64encode(file.read_bytes()).decode("ascii")


def render_gallop(
    binary: str,
    shot: GallopShot,
    dog: DogDesign,
    seconds: int,
    width: int,
    height: int,
    run: Path,
    folder: Path,
) -> Path:
    folder.mkdir()
    deadline = time.monotonic() + 180
    vw = round(width * 360 / height)
    lane = (
        RunningLane(
            binary, run / shot.backdrop, vw, shot.look == "ink", deadline - time.monotonic()
        )
        if shot.backdrop
        else None
    )
    drawings: dict[View, str] = {
        key: _uri(run / drawing.image)
        for key, drawing in dog.head_drawings.get(shot.look, {}).items()
    }
    virtual_width = width * 360 / height
    zoom = height / 360
    with ExitStack() as stack:
        scratch = Path(stack.enter_context(tempfile.TemporaryDirectory(dir=folder)))
        rgb = scratch / "backdrop.rgb"
        stream = stack.enter_context(rgb.open("wb")) if lane else None
        contacts = stack.enter_context((folder / "contacts.jsonl").open("w", encoding="utf8"))
        for index in range(seconds * 24):
            if time.monotonic() >= deadline:
                raise JobTimeoutError(f"gallop exceeded the shot deadline at frame {index}")
            f = running_frame(shot, dog, index, virtual_width)

            def pixels(point: complex, state: GallopFrame = f) -> list[float]:
                pt = state.screen(point) * zoom
                return [round(pt.real, 5), round(pt.imag, 5)]

            if lane and stream:
                stream.write(lane.sample(f.camera * f.facing).tobytes())
            center = f.screen(f.body)
            shadow = ellipse(
                complex(center.real - 2, f.floor_y + 0.2), f.length * 0.59, 4.2, "#635641"
            )
            svg = (
                f'<svg xmlns="http://www.w3.org/2000/svg" '
                'xmlns:xlink="http://www.w3.org/1999/xlink" '
                f'width="{width}" height="{height}" viewBox="0 0 {virtual_width} 360">'
                + countryside(virtual_width, f, shot.look == "ink", lane is not None)
                + f'<g opacity=".23">{shadow}</g>'
                + dog_art(f, dog, shot, drawings.get(f.head_view, ""))
                + "</svg>"
            )
            (folder / f"{index:04}.svg").write_text(svg, encoding="utf8")
            legs = [
                {
                    "root_px": pixels(leg.root),
                    "joint_px": pixels(leg.joint),
                    "ankle_px": pixels(leg.ankle),
                    "paw_px": pixels(leg.tip),
                    "world_paw": [leg.tip.real, leg.tip.imag],
                    "planted": leg.planted,
                }
                for leg in f.legs
            ]
            record = {
                "frame": index,
                "trunk_px": f.length * zoom,
                "facing": f.facing,
                "head_view": f.head_view,
                "camera_px": f.camera * zoom,
                "body_px": pixels(f.body),
                "legs": legs,
            }
            contacts.write(json.dumps(record, separators=(",", ":")) + "\n")
        video = folder / "shot.mp4"
        svg_args = [
            "-f",
            "image2",
            "-framerate",
            "24",
            "-threads",
            "1",
            "-c:v",
            "librsvg",
            "-i",
            str(folder / "%04d.svg"),
        ]
        args = svg_args
        if stream:
            stream.close()
            args = [
                "-f",
                "rawvideo",
                "-framerate",
                "24",
                "-video_size",
                f"{vw}x360",
                "-pix_fmt",
                "rgb24",
                "-i",
                str(rgb),
                *svg_args,
                "-filter_complex_threads",
                "1",
                "-filter_complex",
                f"[0:v]scale={width}:{height}[lane];[lane][1:v]overlay=0:0:format=auto[v]",
                "-map",
                "[v]",
            ]
        result = run_capture(
            [
                binary,
                "-nostdin",
                "-v",
                "error",
                *args,
                "-frames:v",
                str(seconds * 24),
                "-filter_threads",
                "1",
                "-threads",
                "1",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-crf",
                "16",
                str(video),
            ],
            timeout=max(0.001, deadline - time.monotonic()),
        )
        if result.returncode or result.survivors:
            raise ValidationRejected(result.stderr.decode(errors="replace"))
        return video
