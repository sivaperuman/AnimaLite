"""Render ordered shots from ChatGPT artwork through the normal execution service."""

from __future__ import annotations

import shutil
import wave
from pathlib import Path
from tempfile import mkdtemp
from typing import Literal

from pydantic import Field, model_validator

from animalite.canine import DogDesign, GallopShot
from animalite.canine_render import render_gallop, retain_design, retain_image
from animalite.choreography import (
    CharacterDesign,
    Motion,
    builtin_moves,
    check_grip,
    validate_contacts,
)
from animalite.contracts.admission import AdmissionPurpose
from animalite.contracts.assets import AnchorSet, AssetRef, InputAnchor, VideoConditioning
from animalite.contracts.base import Contract, Document, sha256_file
from animalite.contracts.enums import JobState
from animalite.contracts.job import RenderRequest
from animalite.contracts.media import P_L_FINAL_OUTPUT
from animalite.contracts.shot import ShotIntent
from animalite.core.service import LocalExecutionService
from animalite.dog_walk import FRAMES as DOG_WALK_FRAMES
from animalite.dog_walk import DogWalk
from animalite.dog_walk_render import render_dog_walk
from animalite.errors import ValidationRejected
from animalite.gallop_guide import GallopGuide
from animalite.media.cadence import AnchorTiming
from animalite.performance import Mouth, Stage, draw_mouths, render_stage, speech_cues
from animalite.story_archive import finish_story
from animalite.story_media import (
    AUDIO_RATE,
    Camera,
    Dialogue,
    Voice,
    ffmpeg,
    frame_shot,
    mix_shot,
)


class Pose(Contract):
    image: Path
    frame: int = Field(ge=0)


class StoryShot(Contract):
    action: str = Field(min_length=1)
    seconds: int = Field(ge=1, le=10)
    timing: AnchorTiming = AnchorTiming.LINEAR
    controls: dict[str, float | int | str | bool] = Field(default_factory=dict)
    conditioning: VideoConditioning | None = None
    camera: Camera = Camera()
    dialogue: list[Dialogue] = Field(default_factory=list)
    poses: list[Pose] = Field(default_factory=list, max_length=4)
    stage: Stage | None = None
    dog_walk: DogWalk | None = None
    gallop: GallopShot | None = None
    mouths: dict[str, Mouth] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_timing(self) -> StoryShot:
        frames = [pose.frame for pose in self.poses]
        end = self.seconds * P_L_FINAL_OUTPUT.cadence.animation_fps - 1
        if self.controls and (not self.poses or "timing" in self.controls):
            raise ValueError("shot controls require image poses; use the timing field for timing")
        if self.conditioning and (
            not self.poses or set(self.conditioning.anchor_strengths) - set(frames)
        ):
            raise ValueError("neural conditioning requires image poses at the named frame indices")
        if self.gallop:
            if self.dog_walk or self.stage or self.poses or self.mouths:
                raise ValueError("gallop is a self-contained Studio action")
            if self.camera != Camera() or self.timing != AnchorTiming.LINEAR:
                raise ValueError(
                    "use gallop.camera_follow and gallop.speed to direct the camera and pace"
                )
            if (
                self.gallop.performance
                and self.gallop.performance.settled_frame >= self.seconds * 24
            ):
                raise ValueError("gallop performance extends beyond the shot")
            if any(cue.frame >= self.seconds * 24 for cue in self.gallop.head_cues):
                raise ValueError("gallop head cue extends beyond the shot")
        elif self.dog_walk:
            if self.stage or self.poses or self.mouths:
                raise ValueError("dog_walk is a self-contained Studio action")
            if self.camera != Camera() or self.timing != AnchorTiming.LINEAR:
                raise ValueError("dog_walk owns its camera and timing; use launch_frame to retime")
            if self.dog_walk.start_frame + self.seconds * 24 > DOG_WALK_FRAMES:
                raise ValueError("dog_walk slice exceeds the ten-second action")
        elif self.seconds > 6:
            raise ValueError("pose and 3D stage shots must be at most six seconds")
        elif self.stage:
            if self.poses or self.mouths:
                raise ValueError(
                    "3D stage shots use geometry and mesh mouths; omit poses and mouths"
                )
            if (self.camera.focus_x, self.camera.focus_y) != (0.5, 0.5):
                raise ValueError("use orbit.target to aim the 3D camera")
        elif (
            len(frames) < 2 or frames != sorted(set(frames)) or frames[0] != 0 or frames[-1] != end
        ):
            raise ValueError(f"pose frames must increase strictly from 0 to {end}")
        if any(line.start_ms >= self.seconds * 1000 for line in self.dialogue):
            raise ValueError("dialogue must start within its shot")
        return self


class Storyboard(Document):
    dogs: dict[str, DogDesign] = Field(default_factory=dict)
    cast: dict[str, CharacterDesign] = Field(default_factory=dict)
    gallop_guides: dict[str, GallopGuide] = Field(default_factory=dict)
    moves: dict[str, Motion] = Field(default_factory=dict)
    height: Literal[360, 640, 720, 1080, 1280] = 360
    aspect_ratio: Literal["16:9", "9:16"] = "16:9"
    story: str = Field(min_length=1)
    voices: dict[str, Voice] = Field(default_factory=dict)
    shots: list[StoryShot] = Field(min_length=1)

    @property
    def width(self) -> int:
        return self.height * 9 // 16 if self.aspect_ratio == "9:16" else self.height * 16 // 9

    def directed_gallop(self, shot: GallopShot) -> GallopShot:
        if shot.guide_name is None or shot.performance is None:
            return shot
        guide = self.gallop_guides.get(shot.guide_name)
        if guide is None:
            raise ValueError(f"unknown gallop guide {shot.guide_name}")
        action = type(shot.performance).model_validate(
            {**shot.performance.model_dump(), "pose_guide": guide}
        )
        return shot.model_copy(update={"performance": action, "guide_name": None})

    def directed_stage(self, stage: Stage, frames: int) -> Stage:
        actors = {}
        for name, actor in stage.actors.items():
            if actor.design is not None:
                if actor.design not in self.cast:
                    raise ValueError(f"unknown cast design {actor.design}")
                actor = actor.model_copy(update=self.cast[actor.design].model_dump())
            motion = actor.motion
            if actor.move is not None:
                clip = self.moves.get(actor.move) or builtin_moves().get(actor.move)
                if clip is None:
                    raise ValueError(f"unknown performance {actor.move}")
                overrides = {k: v for k, v in motion.tracks().items() if v} if motion else {}
                motion = clip.model_copy(update=overrides)
            if motion:
                for beats in motion.tracks().values():
                    if beats and beats[-1].end > frames:
                        raise ValueError(f"{name}: beat extends beyond the shot")
                for beat in [*motion.left_hand, *motion.right_hand, *motion.eyes, *motion.head]:
                    target = beat.target
                    if target.actor is not None and target.actor not in stage.actors:
                        raise ValueError(f"unknown target actor {target.actor}")
                    if target.prop is not None:
                        check_grip(stage.props, target.prop, target.grip)
            actors[name] = actor.model_copy(update={"motion": motion, "move": None, "design": None})
        validate_contacts(stage.contacts, stage.props, set(actors), frames)
        return stage.model_copy(update={"actors": actors})

    @model_validator(mode="after")
    def require_cast_voices(self) -> Storyboard:
        portrait = self.aspect_ratio == "9:16"
        if portrait != (self.height in (640, 1280)):
            raise ValueError(
                "portrait heights are 640 and 1280; landscape heights are 360, 720 and 1080"
            )
        if any(shot.dog_walk for shot in self.shots) and not portrait:
            raise ValueError("dog_walk requires a 9:16 storyboard")
        if self.height != 360 and any(
            not (shot.stage or shot.dog_walk or shot.gallop) for shot in self.shots
        ):
            raise ValueError(
                "native HD and portrait require staged shots throughout the storyboard"
            )
        for shot in self.shots:
            if shot.gallop and shot.gallop.guide_name:
                self.directed_gallop(shot.gallop)
            if shot.gallop and shot.gallop.dog not in self.dogs:
                raise ValueError(f"unknown dog design {shot.gallop.dog}")
            if shot.gallop and shot.gallop.handler and shot.gallop.handler.actor not in self.cast:
                raise ValueError(f"unknown handler {shot.gallop.handler.actor}")
            if shot.stage:
                self.directed_stage(shot.stage, shot.seconds * 24)
            for line in shot.dialogue:
                if (
                    line.audio is None
                    and line.vocalization is None
                    and line.character not in self.voices
                ):
                    raise ValueError(f"no voice assigned to {line.character!r}")
        return self


def retain_conditioning(
    guide: VideoConditioning | None, source_root: Path, run: Path
) -> tuple[VideoConditioning | None, VideoConditioning | None]:
    """Keep portable asset references and bind the same bytes to this render request."""
    if guide is None:
        return None, None
    retained = {}
    resolved = {}
    for role, asset in guide.assets().items():
        ext = ".mp4" if role.endswith("video") else ".png"
        rel = Path("artwork") / (asset.content_hash.removeprefix("sha256:") + ext)
        dest = run / rel
        dest.parent.mkdir(exist_ok=True)
        if not dest.exists():
            shutil.copyfile(source_root / asset.path, dest)
        if sha256_file(str(dest)) != asset.content_hash:
            raise ValidationRejected(f"changed conditioning asset for {role}")
        retained[role] = asset.model_copy(update={"path": str(rel)})
        resolved[role] = asset.model_copy(update={"path": str(dest.resolve())})
    return guide.model_copy(update=retained), guide.model_copy(update=resolved)


def render_story(manifest: Path, workspace: Path, profile: str, purpose: AdmissionPurpose) -> Path:
    """Each invocation owns a fresh directory; publish only a verified complete movie."""
    board = Storyboard.model_validate_json(manifest.read_bytes())
    if not profile and any(shot.poses for shot in board.shots):
        raise ValidationRejected("illustrated pose shots require an explicit --profile")
    workspace.mkdir(parents=True, exist_ok=True)
    run = Path(mkdtemp(prefix="story-", dir=workspace)).resolve()
    prepared_shots: list[StoryShot] = []
    dogs = {
        name: retain_design(design, manifest.parent, run) for name, design in board.dogs.items()
    }
    service = LocalExecutionService(run / "jobs")
    binary = service.tools.ffmpeg_path
    playlist: list[Path] = []
    voiced_shots: list[StoryShot] = []
    has_dialogue = any(shot.dialogue for shot in board.shots)
    if has_dialogue:
        soundtrack = run / "dialogue.wav"
        with wave.open(str(soundtrack), "wb") as track:
            track.setparams((1, 2, AUDIO_RATE, 0, "NONE", "not compressed"))
            for number, shot in enumerate(board.shots, 1):
                lines = mix_shot(
                    service.tools,
                    manifest.parent,
                    run,
                    number,
                    shot.seconds,
                    shot.dialogue,
                    board.voices,
                    track,
                )
                voiced_shots.append(shot.model_copy(update={"dialogue": lines}))
    for number, shot in enumerate(voiced_shots if has_dialogue else board.shots, 1):
        cues = (
            speech_cues(run, shot.dialogue, shot.seconds)
            if shot.mouths or shot.stage or shot.dog_walk
            else {}
        )
        if shot.gallop:
            action = shot.gallop
            if action.backdrop:
                action = action.model_copy(
                    update={"backdrop": retain_image(action.backdrop, manifest.parent, run)}
                )
            video = render_gallop(
                binary,
                board.directed_gallop(action),
                dogs[action.dog],
                shot.seconds,
                board.width,
                board.height,
                run,
                run / f"gallop-{number}",
                board.cast[action.handler.actor] if action.handler else None,
            )
            prepared_shots.append(shot.model_copy(update={"gallop": action}))
            playlist.append(video.relative_to(run))
            continue
        if shot.dog_walk:
            video = render_dog_walk(
                binary, shot.dog_walk, shot.seconds, board.width, run / f"dog-walk-{number}", cues
            )
            prepared_shots.append(shot)
            playlist.append(video.relative_to(run))
            continue
        if shot.stage is not None:
            video, stage = render_stage(
                binary,
                board.directed_stage(shot.stage, shot.seconds * 24),
                shot.camera,
                shot.seconds,
                manifest.parent,
                run,
                number,
                cues,
                board.height,
                board.width,
            )
            prepared_shots.append(shot.model_copy(update={"stage": stage}))
            playlist.append(video.relative_to(run))
            continue
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
            ffmpeg(
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
        stored_guide, resolved_guide = retain_conditioning(shot.conditioning, manifest.parent, run)
        prepared_shots.append(
            shot.model_copy(update={"poses": prepared_poses, "conditioning": stored_guide})
        )
        request = RenderRequest(
            request_id=f"shot-{number}",
            engine_profile_id=profile,
            execution_purpose=purpose,
            conditioning=resolved_guide,
            shot=ShotIntent(
                shot_code=f"shot-{number}",
                target_duration_seconds=shot.seconds,
                motion_description=shot.action,
                camera=shot.camera.angle,
            ),
            controls={
                **shot.controls,
                **({"timing": shot.timing} if shot.timing != "linear" else {}),
            },
            anchors=AnchorSet(anchors=anchors),
            output=output,
        )
        result = service.render_blocking(request)
        if result.state != JobState.SUCCEEDED or result.output is None:
            raise ValidationRejected(
                f"shot {number} failed ({result.attempt_id}): {result.failure}"
            )
        video = Path(result.output.path)
        if shot.mouths:
            video = draw_mouths(binary, video, run, number, shot.seconds, shot.mouths, cues)
        clip = frame_shot(
            binary,
            video,
            run / f"camera-{number}.mp4",
            shot.camera,
            shot.seconds,
        ).relative_to(run)
        playlist.append(clip)
    prepared = board.model_copy(update={"shots": prepared_shots, "dogs": dogs})
    return finish_story(run, prepared, playlist, service.tools)
