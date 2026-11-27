"""Bounded directions for one existing shot. Revisions are new, replayable runs."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from tempfile import mkdtemp

from pydantic import Field, model_validator

from animalite.canine import GallopShot, HeadCue
from animalite.canine_render import render_gallop
from animalite.contracts.base import Document, sha256_file
from animalite.core.service import LocalExecutionService
from animalite.errors import ValidationRejected
from animalite.story import Storyboard
from animalite.story_archive import StoryIndex, clip_paths, finish_story, index_story, retained_file


class ShotEdit(Document):
    shot: int = Field(ge=1, description="One-based shot number")
    launch_frame: int | None = Field(default=None, ge=0)
    acceleration_frames: int | None = Field(default=None, ge=2)
    brake_frame: int | None = Field(default=None, ge=0)
    braking_frames: int | None = Field(default=None, ge=2)
    turn_frames: int | None = Field(default=None, ge=6)
    surprise_hold_frames: int | None = Field(default=None, ge=0, le=120)
    speed: float | None = Field(default=None, ge=0.8, le=5)
    head_cues: list[HeadCue] | None = None

    @model_validator(mode="after")
    def changed(self) -> ShotEdit:
        if not self.changes():
            raise ValueError("specify at least one shot control")
        return self

    def changes(self) -> dict[str, object]:
        return self.model_dump(exclude={"shot", "schema_version"}, exclude_none=True)


def shot_action(board: Storyboard, number: int) -> GallopShot:
    if not 1 <= number <= len(board.shots) or not (g := board.shots[number - 1].gallop):
        raise ValidationRejected("select an existing gallop shot")
    return g


def from_instruction(board: Storyboard, number: int, instruction: str) -> ShotEdit:
    """Small offline vocabulary. ChatGPT can express other supported edits directly as JSON."""
    g = shot_action(board, number)
    values: dict[str, object] = {"shot": number}
    for clause in re.split(r"\s+and\s+|,\s*", instruction.lower().strip().rstrip(".")):
        if clause in {"make the launch quicker", "make the launch faster"} and g.performance:
            values["acceleration_frames"] = max(2, round(g.performance.acceleration_frames * 0.65))
        elif (
            m := re.fullmatch(r"(?:start|move) the launch (\d+) frames? (earlier|later)", clause)
        ) and g.performance:
            values["launch_frame"] = g.performance.launch_frame + int(m[1]) * (
                -1 if m[2] == "earlier" else 1
            )
        elif (
            m := re.fullmatch(r"hold the surprised look(?: (\d+) frames?)? longer", clause)
        ) and g.handler:
            values["surprise_hold_frames"] = g.handler.surprise_hold_frames + int(m[1] or 12)
        else:
            raise ValidationRejected(
                f"unsupported direction {clause!r}; use a structured shot edit"
            )
    return ShotEdit.model_validate(values)


def apply_edit(board: Storyboard, edit: ShotEdit) -> Storyboard:
    shot = shot_action(board, edit.shot)
    data = board.model_dump(mode="json")
    action = data["shots"][edit.shot - 1]["gallop"]
    for key, value in edit.changes().items():
        if key in {"head_cues", "speed"}:
            action[key] = value
        elif key == "surprise_hold_frames" and shot.handler:
            action["handler"][key] = value
        elif key != "surprise_hold_frames" and shot.performance:
            action["performance"][key] = value
        else:
            raise ValidationRejected(f"{key} requires the corresponding handler or performance")
    result = Storyboard.model_validate(data)
    if result == board:
        raise ValidationRejected("the requested values already apply to this shot")
    return result


def revise_story(
    parent: Path,
    workspace: Path,
    *,
    edit_file: Path | None = None,
    instruction: str | None = None,
    shot_number: int | None = None,
) -> Path:
    if not parent.is_dir() and (parent.name != "story.mp4" or not parent.is_file()):
        raise ValidationRejected("supply a retained run directory or its completed story.mp4")
    root = (parent if parent.is_dir() else parent.parent).resolve(strict=True)
    retained_file(root, Path("story.mp4"))
    board = Storyboard.model_validate_json(
        retained_file(root, Path("storyboard.json")).read_bytes()
    )
    if edit_file and shot_number is None and not instruction:
        edit = ShotEdit.model_validate_json(edit_file.read_bytes())
    elif instruction and shot_number is not None and not edit_file:
        edit = from_instruction(board, shot_number, instruction)
    else:
        raise ValidationRejected("use --edit or supply both --shot and --instruction")
    revised = apply_edit(board, edit)
    clips = clip_paths(root)
    current = index_story(root, board, clips)
    idx = root / "shot-index.json"
    if idx.exists() and current != StoryIndex.model_validate_json(idx.read_bytes()):
        raise ValidationRejected("retained inputs or clips changed since the previous render")
    workspace.mkdir(parents=True, exist_ok=True)
    run = Path(mkdtemp(prefix="story-", dir=workspace)).resolve()
    target = clips[edit.shot - 1]
    for name, digest in current.digests.items():
        rel = Path(name)
        if rel in {target, Path("storyboard.json")}:
            continue
        dest = run / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(retained_file(root, rel), dest)
        if sha256_file(str(dest)) != digest:
            raise ValidationRejected(f"retained file changed while copying {rel}")
    for i, s in enumerate(board.shots, 1):
        if i != edit.shot and (s.gallop or s.dog_walk):
            rel = clips[i - 1].parent / "contacts.jsonl"
            if (root / rel).is_file():
                shutil.copyfile(retained_file(root, rel), run / rel)
    service = LocalExecutionService(run / "jobs")
    g = shot_action(revised, edit.shot)
    video = render_gallop(
        service.tools.ffmpeg_path,
        g,
        revised.dogs[g.dog],
        revised.shots[edit.shot - 1].seconds,
        revised.width,
        revised.height,
        run,
        run / f"gallop-{edit.shot}",
        revised.cast[g.handler.actor] if g.handler else None,
    )
    clips[edit.shot - 1] = video.relative_to(run)
    (run / "revision.json").write_text(
        json.dumps(
            {
                "edit": edit.to_json_obj(),
                "instruction": instruction,
                "parent_storyboard": current.digests["storyboard.json"],
                "reused_shots": [i for i in range(1, len(clips) + 1) if i != edit.shot],
                "original_clip": current.digests[str(target)],
                "revised_clip": sha256_file(str(video)),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return finish_story(run, revised, clips, service.tools)
