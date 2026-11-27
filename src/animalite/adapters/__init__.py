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
from animalite.adapters.rife_ncnn import RIFE_ADAPTER_KEY, RIFE_PROFILE, RifeNcnnAdapter
from animalite.adapters.rife_runtime import PINNED_MODELS, RifeRuntime

__all__ = [
    "FIXTURE_ADAPTER_KEY",
    "FIXTURE_PROFILE",
    "NON_QUALIFYING_REASON",
    "PINNED_MODELS",
    "RIFE_ADAPTER_KEY",
    "RIFE_PROFILE",
    "AdapterContext",
    "FixtureAdapter",
    "MotionAdapter",
    "Registry",
    "RifeNcnnAdapter",
    "RifeRuntime",
    "default_registry",
]
