"""Audio-driven mouth cues, 2D mouth compositing and optional Blender stage rendering."""

from __future__ import annotations

import json
import shutil
import struct
import wave
from pathlib import Path
from typing import Annotated, Literal

import numpy as np
from numpy.typing import NDArray
from pydantic import Field, FiniteFloat, model_validator

from animalite.contracts.base import Contract
from animalite.errors import ValidationRejected
from animalite.proc import run_capture
from animalite.story_media import AUDIO_RATE, Camera, Dialogue, ffmpeg

Unit = Annotated[float, Field(ge=0, le=1)]
Color = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]
Vec3 = tuple[FiniteFloat, FiniteFloat, FiniteFloat]
Cue = tuple[float, float, float]  # jaw open, lip rounding, lip spread
REST: Cue = (0.0, 0.0, 0.0)


class Mouth(Contract):
    """Anchor coordinates in the normalized shot canvas, before digital zoom."""

    at: tuple[Unit, Unit]
    end: tuple[Unit, Unit] | None = None
    width_px: int = Field(default=24, ge=4, le=180)
    ink: Color = "#372630"


SignedUnit = Annotated[float, Field(ge=-1, le=1)]
Distance = Annotated[float, Field(gt=0.05, le=1000)]


class ActingPose(Contract):
    at: Unit
    head_turn: SignedUnit = 0
    head_tilt: SignedUnit = 0
    gaze: SignedUnit = 0
    brow: SignedUnit = 0
    smile: SignedUnit = 0
    blink: Unit = 0
    raise_hand: Unit = 0
    squash: SignedUnit = 0


class Cinema(Contract):
    samples: int = Field(default=12, ge=1, le=128)
    lighting: Literal["daylight", "sunset"] = "daylight"
    set: Literal["studio", "workshop", "asset"] = "studio"
    focus_distance: tuple[Distance, Distance] | None = None
    f_stop: float = Field(default=2.8, ge=0.7, le=32)
    shutter: Unit = 0
    ease_camera: bool = True
    denoise: bool = True


class Actor(Contract):
    x: FiniteFloat = 0
    y: FiniteFloat = 0
    skin: Color = "#94B979"
    shirt: Color = "#E69345"
    costume: Literal["cap", "forelock"] = "forelock"
    acting: list[ActingPose] = Field(default_factory=list)

    @model_validator(mode="after")
    def ordered_poses(self) -> Actor:
        times = [pose.at for pose in self.acting]
        if times != sorted(set(times)):
            raise ValueError("acting pose times must increase strictly")
        return self


class Orbit(Contract):
    target: Vec3 = (0, 0, 1.2)
    radius: float = Field(default=4.8, gt=0.1, le=1000)
    yaw: tuple[FiniteFloat, FiniteFloat] = (0, 0)
    pitch: tuple[
        Annotated[float, Field(gt=-89.9, lt=89.9)], Annotated[float, Field(gt=-89.9, lt=89.9)]
    ] = (6, 6)
    roll: tuple[FiniteFloat, FiniteFloat] = (0, 0)


class Stage(Contract):
    orbit: Orbit = Orbit()
    cinema: Cinema | None = None
    actors: dict[str, Actor] = Field(default_factory=dict)
    model: Path | None = None
    # Character -> imported mesh with AL_open, AL_round, AL_wide shape keys.
    bindings: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def scene_source(self) -> Stage:
        if bool(self.actors) == (self.model is not None):
            raise ValueError("choose either built-in actors or an embedded GLB model")
        if self.cinema is None and any(
            a.acting or a.costume != "forelock" for a in self.actors.values()
        ):
            raise ValueError("costumes and acting poses require stage.cinema")
        if self.cinema and self.cinema.set == "asset" and self.model is None:
            raise ValueError("the asset set requires a GLB scene")
        if self.actors and self.bindings:
            raise ValueError("mesh bindings apply only to a GLB")
        if len(set(self.bindings.values())) != len(self.bindings):
            raise ValueError("each speaking character needs its own mouth mesh")
        return self


def speech_cues(run: Path, lines: list[Dialogue], seconds: int) -> dict[str, list[Cue]]:
    """Estimate three continuous mouth weights per frame from each isolated voice."""
    count = seconds * 24
    stems: dict[str, NDArray[np.float64]] = {}
    for line in lines:
        assert line.audio is not None  # normalized by mix_shot
        with wave.open(str(run / line.audio), "rb") as sound:
            samples = np.frombuffer(sound.readframes(sound.getnframes()), dtype="<i2")
        stem = stems.setdefault(line.character, np.zeros(seconds * AUDIO_RATE))
        offset = line.start_ms * AUDIO_RATE // 1000
        stem[offset : offset + len(samples)] += samples.astype(float) / 32768

    cues: dict[str, list[Cue]] = {}
    window = np.hanning(AUDIO_RATE // 24)
    hz = np.fft.rfftfreq(len(window), 1 / AUDIO_RATE)
    for speaker, stem in stems.items():
        blocks = stem.reshape(count, -1)
        level = np.sqrt(np.mean(blocks**2, axis=1))
        # Reference only active frames so long leading/trailing pauses do not boost noise.
        active = level[level > 0.003]
        reference = max(0.02, float(np.percentile(active, 85))) if active.size else 0.02
        shapes: list[Cue] = []
        for block, rms in zip(blocks, level, strict=True):
            if rms < max(0.002, reference * 0.045):
                shapes.append(REST)
                continue
            power = abs(np.fft.rfft(block * window)) ** 2
            low = power[(hz >= 180) & (hz < 1000)].sum()
            mid = power[(hz >= 1000) & (hz < 3000)].sum()
            high = power[(hz >= 3000) & (hz < 8000)].sum()
            total = low + mid + high + 1e-12
            energy = min(1.0, float(rms / reference)) ** 0.65
            shapes.append(
                (
                    energy * (1 - 0.65 * high / total),
                    energy * low / total,
                    energy * (mid + high) / total,
                )
            )
        cues[speaker] = shapes
    return cues


def _stamp(frame: int) -> str:
    ticks = frame * 100 // 24
    return f"0:00:{ticks // 100:02}.{ticks % 100:02}"


def draw_mouths(
    binary: str,
    source: Path,
    run: Path,
    number: int,
    seconds: int,
    mouths: dict[str, Mouth],
    cues: dict[str, list[Cue]],
) -> Path:
    """Render a vector mouth at each delivery timestamp; projection/zoom follows."""
    name = f"mouth-{number}.ass"
    script = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 640",
        "PlayResY: 360",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Mouth,Arial,10,&H00000000,&H00000000,&H00000000,&H00000000,"
        "0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    frames = seconds * 24
    for speaker, mouth in mouths.items():
        end = mouth.end or mouth.at
        ink = mouth.ink[5:7] + mouth.ink[3:5] + mouth.ink[1:3]
        for i, (opened, rounded, wide) in enumerate(cues.get(speaker, [REST] * frames)):
            t = i / (frames - 1)
            x, y = (a + (b - a) * t for a, b in zip(mouth.at, end, strict=True))
            w = max(4, round(mouth.width_px * (1 - 0.35 * rounded + 0.28 * wide)))
            h = max(2, round(mouth.width_px * (0.08 + 0.52 * opened)))
            shape = f"m 0 {h // 2} b 0 0 {w} 0 {w} {h // 2} b {w} {h + 1} 0 {h + 1} 0 {h // 2}"
            style = rf"{{\an7\pos({x * 640 - w / 2:.2f},{y * 360 - h / 2:.2f})\1c&H{ink}&\p1}}"
            script.append(f"Dialogue: 0,{_stamp(i)},{_stamp(i + 1)},Mouth,,0,0,0,,{style}{shape}")
    (run / name).write_text("\n".join(script) + "\n", encoding="utf-8")
    dest = run / f"speaking-{number}.mp4"
    ffmpeg(
        binary,
        [
            "-i",
            str(source),
            "-vf",
            f"ass={name}",
            "-an",
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-threads",
            "2",
            "-pix_fmt",
            "yuv420p",
            dest.name,
        ],
        cwd=run,
    )
    return dest


def render_stage(
    binary: str,
    stage: Stage,
    camera: Camera,
    seconds: int,
    root: Path,
    run: Path,
    number: int,
    cues: dict[str, list[Cue]],
    height: int = 360,
) -> tuple[Path, Stage]:
    blender = shutil.which("blender")
    if not blender:
        raise ValidationRejected("3D shots require Blender 4.3+ on PATH")
    if stage.model:
        model = (root / stage.model).resolve(strict=True)
        with model.open("rb") as stream:
            header = stream.read(20)
            if len(header) != 20 or header[:8] != b"glTF\x02\0\0\0" or header[16:] != b"JSON":
                raise ValidationRejected("stage.model must be a GLB 2.0 file")
            length = struct.unpack_from("<I", header, 12)[0]
            if length > model.stat().st_size - 20:
                raise ValidationRejected("invalid GLB JSON chunk length")
            meta = json.loads(stream.read(length))
        for asset in [*meta.get("buffers", []), *meta.get("images", [])]:
            if "uri" in asset and not asset["uri"].startswith("data:"):
                raise ValidationRejected("embed GLB resources for portable storyboard replay")
        dest = run / f"model-{number}.glb"
        shutil.copyfile(model, dest)
        stage = stage.model_copy(update={"model": Path(dest.name)})
    job = run / f"stage-{number}"
    job.mkdir()
    config = job / "stage.json"
    config.write_text(
        json.dumps(
            {
                "stage": stage.to_json_obj(),
                "camera": camera.to_json_obj(),
                "frames": seconds * 24,
                "height": height,
                "cues": cues,
            }
        ),
        encoding="utf-8",
    )
    result = run_capture(
        [
            blender,
            "--background",
            "--factory-startup",
            "--disable-autoexec",
            "-t",
            "2",
            "--python-exit-code",
            "1",
            "--python",
            str(Path(__file__).with_name("blender_stage.py")),
            "--",
            str(config),
        ],
        timeout=3600 if stage.cinema else 600,
        cwd=run,
    )
    if result.returncode or result.survivors:
        message = (result.stdout + result.stderr).decode(errors="replace")
        raise ValidationRejected(f"Blender shot {number} failed: {message[-2000:]}")
    filters = []
    if stage.cinema and stage.cinema.denoise and (job / "no-native-denoise").exists():
        filters = ["-filter_threads", "2", "-vf", "format=yuv444p,nlmeans=s=5:p=5:r=9"]
    dest = run / f"orbit-{number}.mp4"
    ffmpeg(
        binary,
        [
            "-framerate",
            "24",
            "-start_number",
            "1",
            "-i",
            str(job / "frame-%04d.png"),
            "-frames:v",
            str(seconds * 24),
            *filters,
            "-c:v",
            "libx264",
            "-profile:v",
            "high",
            "-level",
            "4.1" if height == 1080 else "3.1",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-threads",
            "2",
            str(dest),
        ],
    )
    return dest, stage
