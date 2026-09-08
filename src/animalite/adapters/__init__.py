"""Motion adapters. Package A ships one deterministic fixture adapter only."""

from __future__ import annotations

from animalite.adapters.base import AdapterContext, MotionAdapter
from animalite.adapters.fixture import (
    FIXTURE_ADAPTER_KEY,
    FIXTURE_PROFILE,
    NON_QUALIFYING_REASON,
    FixtureAdapter,
)
from animalite.adapters.registry import Registry, default_registry

__all__ = [
    "FIXTURE_ADAPTER_KEY",
    "FIXTURE_PROFILE",
    "NON_QUALIFYING_REASON",
    "AdapterContext",
    "FixtureAdapter",
    "MotionAdapter",
    "Registry",
    "default_registry",
]
