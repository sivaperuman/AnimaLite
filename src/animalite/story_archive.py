"""Verify a complete story and retain the inputs needed for shot-local revisions."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from animalite.contracts.base import Document, sha256_file
from animalite.contracts.media import P_L_FINAL_OUTPUT
from animalite.errors import ValidationRejected
from animalite.media.ffmpeg import FFmpegTools
from animalite.media.probe import probe_output, validate_output
from animalite.story_media import ffmpeg, verify_dialogue

if TYPE_CHECKING:
    from animalite.story import Storyboard


def retained_file(root: Path, relative: Path) -> Path:
    if relative.is_absolute() or ".." in relative.parts:
        raise ValidationRejected(f"invalid retained path {relative}")
    path = (root / relative).resolve(strict=True)
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValidationRejected(f"missing retained file {relative}")
    return path


def clip_paths(root: Path) -> list[Path]:
    paths = []
    for line in (root / "shots.ffconcat").read_text().splitlines():
        m = re.fullmatch(r"file '([a-zA-Z0-9_./-]+)'", line)
        if not m:
            raise ValidationRejected("invalid retained shot playlist")
        rel = Path(m[1])
        retained_file(root, rel)
        paths.append(rel)
    return paths


class StoryIndex(Document):
    clips: list[Path]
    digests: dict[str, str]


def index_story(root: Path, board: Storyboard, clips: list[Path]) -> StoryIndex:
    files = set(clips) | {Path("storyboard.json")}
    if any(s.dialogue for s in board.shots):
        files.add(Path("dialogue.wav"))
    for d in board.dogs.values():
        if d.leg_drawing:
            files.add(d.leg_drawing.image)
        files.update(a.image for views in d.head_drawings.values() for a in views.values())
        for a in d.body_drawings.values():
            files.add(a.image)
            if a.ink_image:
                files.add(a.ink_image)
    for shot in board.shots:
        files.update(p.image for p in shot.poses)
        files.update(line.audio for line in shot.dialogue if line.audio)
        if shot.gallop and shot.gallop.backdrop:
            files.add(shot.gallop.backdrop)
        if shot.stage and shot.stage.model:
            files.add(shot.stage.model)
    if len(clips) != len(board.shots) or len(set(clips)) != len(clips):
        raise ValidationRejected("retained shot playlist does not match storyboard")
    return StoryIndex(
        clips=clips,
        digests={str(p): sha256_file(str(retained_file(root, p))) for p in sorted(files)},
    )


def finish_story(run: Path, board: Storyboard, clips: list[Path], tools: FFmpegTools) -> Path:
    (run / "storyboard.json").write_text(board.model_dump_json(indent=2), encoding="utf-8")
    listing = run / "shots.ffconcat"
    listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in clips), encoding="utf-8")
    index = index_story(run, board, clips)
    pending = run / "unverified.mp4"
    has_audio = any(s.dialogue for s in board.shots)
    audio = (
        [
            "-i",
            str(run / "dialogue.wav"),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
        ]
        if has_audio
        else []
    )
    ffmpeg(
        tools.ffmpeg_path,
        [
            "-f",
            "concat",
            "-safe",
            "1",
            "-i",
            str(listing),
            *audio,
            "-c:v",
            "copy",
            "-movflags",
            "+faststart",
            str(pending),
        ],
    )
    duration = sum(s.seconds for s in board.shots)
    expected = P_L_FINAL_OUTPUT.model_copy(
        update={
            "width": board.width,
            "height": board.height,
            "codec_level": "4.1" if board.height == 1080 else "3.1",
            "animation_frame_count": duration * P_L_FINAL_OUTPUT.cadence.animation_fps,
        }
    )
    issues = validate_output(probe_output(tools, pending), expected)
    if issues:
        raise ValidationRejected("; ".join(issues))
    if has_audio:
        verify_dialogue(tools, pending, duration)
    (run / "shot-index.json").write_text(index.model_dump_json(indent=2), encoding="utf-8")
    return pending.rename(run / "story.mp4")
