"""Shot framing and character dialogue for the story renderer."""

from __future__ import annotations

import json
import wave
from fractions import Fraction
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import Field, model_validator

from animalite.contracts.base import Contract
from animalite.errors import ValidationRejected
from animalite.media.ffmpeg import FFmpegTools
from animalite.proc import run_capture

AUDIO_RATE = 48_000
Voice = Literal["kal", "kal16", "awb", "rms", "slt"]


class Camera(Contract):
    angle: str = Field(default="eye-level", min_length=1)
    zoom_start: float = Field(default=1, ge=1, le=4)
    zoom_end: float = Field(default=1, ge=1, le=4)
    focus_x: float = Field(default=0.5, ge=0, le=1)
    focus_y: float = Field(default=0.5, ge=0, le=1)


class Dialogue(Contract):
    character: str = Field(min_length=1)
    start_ms: int = Field(default=0, ge=0)
    text: str | None = Field(default=None, min_length=1)
    audio: Path | None = None

    @model_validator(mode="after")
    def require_line(self) -> Dialogue:
        if self.text is None and self.audio is None:
            raise ValueError("dialogue requires text or a recorded audio file")
        return self


def ffmpeg(binary: str, args: list[str], *, cwd: Path | None = None) -> None:
    result = run_capture([binary, "-nostdin", "-loglevel", "error", *args], timeout=120.0, cwd=cwd)
    if result.returncode or result.survivors:
        raise ValidationRejected(
            f"story media step failed: {result.stderr.decode(errors='replace')}"
        )


def frame_shot(binary: str, video: Path, dest: Path, camera: Camera, seconds: int) -> Path:
    if camera.zoom_start == camera.zoom_end == 1:
        return video
    # Use the delivery frame index, including both endpoints. Supersampling
    # reduces integer crop jumps during slow moves.
    progress = f"(on/{seconds * 24 - 1})"
    zoom = f"{camera.zoom_start}+({camera.zoom_end}-{camera.zoom_start})*{progress}"
    framing = (
        f"scale=1280:720,zoompan=z='{zoom}':x='(iw-iw/zoom)*{camera.focus_x}'"
        f":y='(ih-ih/zoom)*{camera.focus_y}':d=1:s=640x360:fps=24,setsar=1"
    )
    ffmpeg(
        binary,
        [
            "-i",
            str(video),
            "-an",
            "-vf",
            framing,
            "-c:v",
            "libx264",
            "-profile:v",
            "high",
            "-level",
            "3.1",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-threads",
            "2",
            str(dest),
        ],
    )
    return dest


def mix_shot(
    tools: FFmpegTools,
    root: Path,
    run: Path,
    number: int,
    seconds: int,
    lines: list[Dialogue],
    voices: dict[str, Voice],
    track: wave.Wave_write,
) -> list[Dialogue]:
    """Write a shot of PCM (including silence) and retain replayable per-line audio."""
    mixed = np.zeros(seconds * AUDIO_RATE, dtype=np.int32)
    prepared: list[Dialogue] = []
    for i, line in enumerate(lines, 1):
        stem = f"shot-{number}-line-{i}"
        if line.audio is not None:
            source = (root / line.audio).resolve(strict=True)
            demux = {".wav": "wav", ".mp3": "mp3", ".flac": "flac"}.get(source.suffix.lower())
            if not source.is_file() or demux is None:
                raise ValidationRejected(f"expected a WAV, MP3 or FLAC voice recording: {source}")
            inputs = ["-f", demux, "-i", str(source), "-map", "0:a:0"]
        else:
            (run / f"{stem}.txt").write_text(line.text or "", encoding="utf-8")
            inputs = [
                "-f",
                "lavfi",
                "-i",
                f"flite=voice={voices[line.character]}:textfile={stem}.txt",
            ]
        dest = run / f"{stem}.wav"
        ffmpeg(
            tools.ffmpeg_path,
            [
                *inputs,
                "-t",
                str(seconds + 1),
                "-ar",
                str(AUDIO_RATE),
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                dest.name,
            ],
            cwd=run,
        )
        with wave.open(str(dest), "rb") as sound:
            samples = np.frombuffer(sound.readframes(sound.getnframes()), dtype="<i2")
        offset = line.start_ms * AUDIO_RATE // 1000
        if not samples.size or offset + samples.size > mixed.size:
            raise ValidationRejected(
                f"shot {number}, {line.character}: empty line or dialogue extends past shot end"
            )
        mixed[offset : offset + samples.size] += samples
        prepared.append(line.model_copy(update={"audio": Path(dest.name)}))
    maximum = max(32767, int(np.abs(mixed).max()))
    track.writeframes((mixed * (32767 / maximum)).astype("<i2").tobytes())
    return prepared


def verify_dialogue(tools: FFmpegTools, movie: Path, seconds: int) -> None:
    result = run_capture(
        [
            tools.ffprobe_path,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_name,time_base,duration_ts,sample_rate",
            "-of",
            "json",
            str(movie),
        ],
        timeout=120,
    )
    if result.returncode or result.survivors:
        raise ValidationRejected("could not probe the story dialogue track")
    tracks = json.loads(result.stdout)["streams"]
    if len(tracks) != 1:
        raise ValidationRejected("story dialogue track missing")
    audio = tracks[0]
    if (
        audio["codec_name"] != "aac"
        or int(audio["sample_rate"]) != AUDIO_RATE
        or int(audio["duration_ts"]) * Fraction(audio["time_base"]) != seconds
    ):
        raise ValidationRejected("unexpected story dialogue format or duration")
    ffmpeg(tools.ffmpeg_path, ["-xerror", "-i", str(movie), "-map", "0:a:0", "-f", "null", "-"])
