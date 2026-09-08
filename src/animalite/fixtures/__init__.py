"""Reproducible synthetic fixtures. Test material, never benchmark evidence."""

from __future__ import annotations

from animalite.fixtures.generator import (
    FIXTURE_CLIPS,
    FixtureClip,
    generate_clip,
    write_anchor_set,
)

__all__ = ["FIXTURE_CLIPS", "FixtureClip", "generate_clip", "write_anchor_set"]
