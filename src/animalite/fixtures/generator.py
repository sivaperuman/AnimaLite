"""Reproducible synthetic anchor generator.

Produces flat-shaded, stylized-2D-looking anchor frames from a seed and a clip
definition, so the whole pipeline can be exercised with no private artwork, no
download and no model weights. Output is byte-deterministic for a given
(seed, clip, geometry): the same command on the same FFmpeg build produces the
same PNG hashes.

This artwork is a **test fixture**. It is not a section 12.0 benchmark clip, and
the clips defined here are deliberately not the locked 12-clip qualification
sample.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from animalite.contracts.assets import AnchorSet, AssetRef, InputAnchor
from animalite.contracts.base import sha256_file
from animalite.media.ffmpeg import FFmpegTools
from animalite.media.image import write_png_rgb24

__all__ = ["FIXTURE_CLIPS", "FixtureClip", "generate_clip", "write_anchor_set"]


@dataclass(frozen=True)
class FixtureClip:
    """A deterministic synthetic clip definition."""

    clip_id: str
    seed: int
    anchor_indices: tuple[int, ...]
    animation_frame_count: int = 72
    description: str = ""

    @property
    def anchor_count(self) -> int:
        return len(self.anchor_indices)


#: Small development fixtures. Not the section 12.0 locked sample.
FIXTURE_CLIPS: dict[str, FixtureClip] = {
    c.clip_id: c
    for c in (
        FixtureClip(
            clip_id="fixture-two-anchor",
            seed=1,
            anchor_indices=(0, 71),
            description="Two-anchor endpoint case: 0 and 71 only.",
        ),
        FixtureClip(
            clip_id="fixture-three-anchor",
            seed=2,
            anchor_indices=(0, 35, 71),
            description="Three anchors with one mid-clip approved frame.",
        ),
        FixtureClip(
            clip_id="fixture-four-anchor",
            seed=3,
            anchor_indices=(0, 24, 48, 71),
            description="Four anchors: the section 12.0 upper input bound.",
        ),
        FixtureClip(
            clip_id="fixture-preview",
            seed=4,
            anchor_indices=(0, 35),
            animation_frame_count=36,
            description="Preview-shaped fixture: 36 animation frames (3 seconds).",
        ),
    )
}


def _render_anchor(
    clip: FixtureClip, animation_index: int, width: int, height: int
) -> NDArray[np.uint8]:
    """Render one flat-shaded synthetic anchor deterministically.

    Uses only closed-form arithmetic on the (clip, index) pair -- no RNG state
    carried between frames -- so any single anchor can be regenerated on its own
    and match bit for bit.
    """
    rng = np.random.default_rng(clip.seed)
    palette = (rng.integers(40, 215, size=(4, 3)) & 0xFE).astype(np.uint8)
    span = max(1, clip.animation_frame_count - 1)
    t = animation_index / span

    frame = np.empty((height, width, 3), dtype=np.uint8)
    frame[:, :, :] = palette[0]

    # Ground band: a hard horizon line, no gradient, so the fixture stays flat 2D.
    horizon = int(height * 0.72)
    frame[horizon:, :, :] = palette[1]

    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)

    # Character disc travelling left to right with a vertical bob.
    radius = height * 0.16
    cx = width * (0.22 + 0.56 * t)
    cy = height * (0.44 - 0.06 * math.sin(math.pi * t))
    disc = ((xx - cx) ** 2 + (yy - cy) ** 2) <= radius**2
    frame[disc] = palette[2]

    # Signature accessory: a square prop rotating position around the disc.
    prop = height * 0.07
    px = cx + radius * 0.95 * math.cos(2.0 * math.pi * t)
    py = cy - radius * 0.95 * math.sin(2.0 * math.pi * t)
    box = (np.abs(xx - px) <= prop / 2) & (np.abs(yy - py) <= prop / 2)
    frame[box] = palette[3]

    # Fixed reference bar: an unmoving element whose drift would reveal a
    # pipeline geometry error.
    bar_h = max(2, height // 60)
    frame[2 : 2 + bar_h, 2 : 2 + width // 6, :] = palette[3]
    return frame


#: Per-image bound for fixture generation. Not a job deadline: the generator
#: runs outside the execution service, so it owns this allowance explicitly.
FIXTURE_WRITE_TIMEOUT_SECONDS = 60.0


def generate_clip(
    clip: FixtureClip,
    out_dir: Path,
    *,
    width: int = 640,
    height: int = 360,
    tools: FFmpegTools | None = None,
) -> AnchorSet:
    """Generate a clip's anchors as PNGs and return the validated anchor set."""
    resolved = (tools or FFmpegTools.discover()).require()
    out_dir.mkdir(parents=True, exist_ok=True)
    anchors: list[InputAnchor] = []
    for animation_index in clip.anchor_indices:
        frame = _render_anchor(clip, animation_index, width, height)
        path = out_dir / f"{clip.clip_id}_a{animation_index:03d}.png"
        # An offline generator has no job deadline, so it states its own
        # bound rather than inheriting one: a stalled encoder must not hang
        # a fixture build indefinitely.
        write_png_rgb24(resolved, frame, path, timeout=FIXTURE_WRITE_TIMEOUT_SECONDS)
        anchors.append(
            InputAnchor(
                anchor_id=f"{clip.clip_id}#{animation_index:03d}",
                animation_index=animation_index,
                asset=AssetRef(
                    path=str(path),
                    content_hash=sha256_file(str(path)),
                    size_bytes=path.stat().st_size,
                    media_type="image/png",
                ),
                width=width,
                height=height,
                approved=True,
            )
        )
    return AnchorSet(anchors=anchors)


def write_anchor_set(anchor_set: AnchorSet, destination: Path) -> Path:
    """Write an anchor set as JSON next to its images."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(anchor_set.to_json_obj(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination
