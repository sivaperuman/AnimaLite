"""Render and retain the vector poses and contact tracks for one Studio take."""

from __future__ import annotations

import json
from pathlib import Path

from animalite.dog_walk import FPS, DogWalk, pose
from animalite.dog_walk_art import artwork, project
from animalite.performance import REST, Cue
from animalite.story_media import ffmpeg


def render_dog_walk(
    binary: str,
    action: DogWalk,
    seconds: int,
    width: int,
    folder: Path,
    cues: dict[str, list[Cue]],
) -> Path:
    folder.mkdir()
    frames = seconds * FPS
    mouth = cues.get(action.handler, [REST] * frames)
    scale = width / 360

    def pair(point: complex) -> tuple[float, float]:
        return round(point.real, 3), round(point.imag, 3)

    with (folder / "contacts.jsonl").open("w", encoding="utf-8") as contacts:
        for index in range(frames):
            frame = action.start_frame + index
            p = pose(frame, action)
            (folder / f"{index:04}.svg").write_text(
                artwork(p, action, width, mouth[index]), encoding="utf-8"
            )
            contact = {
                "schema_version": 1,
                "action_frame": frame,
                "canvas_px": [width, width * 16 // 9],
                "handler_px": {
                    name: pair(project(p, action, pt) * scale)
                    for name, pt in (
                        ("face", p.face),
                        ("shoulder", p.shoulder),
                        ("hip", p.hip),
                        ("free_hand", p.free_hand),
                        ("far_foot", p.feet[0]),
                        ("near_foot", p.feet[1]),
                    )
                },
                "dog_px": pair(project(p, action, p.dog) * scale),
                "paws_px": [pair(project(p, action, paw.tip) * scale) for paw in p.paws],
                "lead_px": [
                    pair(project(p, action, pt) * scale)
                    for pt in (p.lead.hand, p.lead.control, p.lead.collar)
                ],
                "paws_stage_px": [pair(paw.tip) for paw in p.paws],
                "planted": [paw.planted for paw in p.paws],
            }
            if p.fall:
                contact["lead_gripped"] = p.fall.slack == 0 and p.fall.release == 0
                contact["prone"] = p.fall.prone
            contacts.write(json.dumps(contact) + "\n")
    output = folder / "shot.mp4"
    ffmpeg(
        binary,
        [
            "-f",
            "image2",
            "-framerate",
            str(FPS),
            "-start_number",
            "0",
            "-threads",
            "1",
            "-c:v",
            "librsvg",
            "-i",
            str(folder / "%04d.svg"),
            "-frames:v",
            str(frames),
            "-filter_threads",
            "1",
            # A single x264 worker makes replay deterministic on the same build.
            "-threads",
            "1",
            "-c:v",
            "libx264",
            "-profile:v",
            "high",
            "-level",
            "3.1",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "18",
            str(output),
        ],
    )
    return output
