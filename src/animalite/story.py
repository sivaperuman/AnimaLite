"""Render ordered shots from ChatGPT artwork through the normal execution service."""

from __future__ import annotations

from pathlib import Path
from tempfile import mkdtemp
from typing import Literal

from pydantic import Field, model_validator

from animalite.contracts.admission import AdmissionPurpose
from animalite.contracts.assets import AnchorSet, AssetRef, InputAnchor
from animalite.contracts.base import Contract, Document, sha256_file
from animalite.contracts.enums import JobState
from animalite.contracts.job import RenderRequest
from animalite.contracts.media import P_L_FINAL_OUTPUT
from animalite.contracts.shot import ShotIntent
from animalite.core.service import LocalExecutionService
from animalite.errors import ValidationRejected
from animalite.media.probe import probe_output, validate_output
from animalite.proc import run_capture


class Pose(Contract):
    image: Path
    frame: int = Field(ge=0)


class StoryShot(Contract):
    action: str = Field(min_length=1)
    seconds: int = Field(ge=1, le=6)
    timing: Literal["linear", "ease-in-out"] = "linear"
    poses: list[Pose] = Field(min_length=2, max_length=4)

    @model_validator(mode="after")
    def check_timing(self) -> StoryShot:
        frames = [pose.frame for pose in self.poses]
        end = self.seconds * P_L_FINAL_OUTPUT.cadence.animation_fps - 1
        if frames != sorted(set(frames)) or frames[0] != 0 or frames[-1] != end:
            raise ValueError(f"pose frames must increase strictly from 0 to {end}")
        return self


class Storyboard(Document):
    story: str = Field(min_length=1)
    shots: list[StoryShot] = Field(min_length=1)


def _ffmpeg(binary: str, args: list[str]) -> None:
    result = run_capture([binary, "-nostdin", "-loglevel", "error", *args], timeout=120.0)
    if result.returncode or result.survivors:
        raise ValidationRejected(
            f"story media step failed: {result.stderr.decode(errors='replace')}"
        )


def render_story(manifest: Path, workspace: Path, profile: str, purpose: AdmissionPurpose) -> Path:
    """Each invocation owns a fresh directory; publish only a verified complete movie."""
    board = Storyboard.model_validate_json(manifest.read_bytes())
    workspace.mkdir(parents=True, exist_ok=True)
    run = Path(mkdtemp(prefix="story-", dir=workspace)).resolve()
    prepared_shots: list[StoryShot] = []
    service = LocalExecutionService(run / "jobs")
    binary = service.tools.ffmpeg_path
    playlist: list[str] = []
    for number, shot in enumerate(board.shots, 1):
        anchors = []
        prepared_poses: list[Pose] = []
        for pose in shot.poses:
            source = (manifest.parent / pose.image).resolve(strict=True)
            decoder = {".png": "png", ".jpg": "mjpeg", ".jpeg": "mjpeg", ".webp": "webp"}.get(
                source.suffix.lower()
            )
            if decoder is None or not source.is_file():
                raise ValidationRejected(f"expected a PNG, JPEG, or WebP still: {source}")
            dest = run / f"shot-{number}-pose-{pose.frame}.png"
            _ffmpeg(
                binary,
                [
                    "-f",
                    "image2",
                    "-pattern_type",
                    "none",
                    "-c:v",
                    decoder,
                    "-i",
                    str(source),
                    "-vf",
                    "scale=640:360:force_original_aspect_ratio=decrease,"
                    "pad=640:360:(ow-iw)/2:(oh-ih)/2,setsar=1,format=rgb24",
                    "-frames:v",
                    "1",
                    "-threads",
                    "1",
                    str(dest),
                ],
            )
            prepared_poses.append(Pose(image=Path(dest.name), frame=pose.frame))
            anchors.append(
                InputAnchor(
                    anchor_id=dest.stem,
                    animation_index=pose.frame,
                    width=640,
                    height=360,
                    asset=AssetRef(
                        path=str(dest),
                        content_hash=sha256_file(str(dest)),
                        size_bytes=dest.stat().st_size,
                        media_type="image/png",
                    ),
                )
            )
        output = P_L_FINAL_OUTPUT.model_copy(
            update={"animation_frame_count": shot.poses[-1].frame + 1}
        )
        prepared_shots.append(shot.model_copy(update={"poses": prepared_poses}))
        request = RenderRequest(
            request_id=f"shot-{number}",
            engine_profile_id=profile,
            execution_purpose=purpose,
            shot=ShotIntent(
                shot_code=f"shot-{number}",
                target_duration_seconds=shot.seconds,
                motion_description=shot.action,
            ),
            controls={"timing": shot.timing} if shot.timing != "linear" else {},
            anchors=AnchorSet(anchors=anchors),
            output=output,
        )
        result = service.render_blocking(request)
        if result.state != JobState.SUCCEEDED or result.output is None:
            raise ValidationRejected(
                f"shot {number} failed ({result.attempt_id}): {result.failure}"
            )
        clip = Path(result.output.path).relative_to(run)
        playlist.append(f"file '{clip.as_posix()}'")
    (run / "storyboard.json").write_text(
        board.model_copy(update={"shots": prepared_shots}).model_dump_json(indent=2),
        encoding="utf-8",
    )
    listing = run / "shots.ffconcat"
    listing.write_text("\n".join(playlist) + "\n", encoding="utf-8")
    pending = run / "unverified.mp4"
    _ffmpeg(
        binary,
        [
            "-f",
            "concat",
            "-safe",
            "1",
            "-i",
            str(listing),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(pending),
        ],
    )
    expected = P_L_FINAL_OUTPUT.model_copy(
        update={"animation_frame_count": sum(shot.poses[-1].frame + 1 for shot in board.shots)}
    )
    issues = validate_output(probe_output(service.tools, pending), expected)
    if issues:
        raise ValidationRejected("; ".join(issues))
    return pending.rename(run / "story.mp4")
