"""Adapter and engine-profile registry.

Profiles are looked up by id and adapters by ``adapter_key``; the core never
imports an adapter module directly, so a learned Package B runtime can be
registered without touching validation, the service or the media pipeline.
"""

from __future__ import annotations

from animalite.adapters.base import MotionAdapter
from animalite.adapters.fixture import FIXTURE_PROFILE, FixtureAdapter
from animalite.adapters.rife_ncnn import RIFE_PROFILE, RifeNcnnAdapter
from animalite.contracts.profile import EngineProfile
from animalite.errors import ProfileNotFoundError

__all__ = ["Registry", "default_registry"]


class Registry:
    """Holds the adapters and engine profiles available to this process."""

    def __init__(self) -> None:
        self._adapters: dict[str, MotionAdapter] = {}
        self._profiles: dict[str, EngineProfile] = {}

    def register_adapter(self, adapter: MotionAdapter) -> None:
        self._adapters[adapter.key] = adapter

    def register_profile(self, profile: EngineProfile) -> None:
        if profile.adapter_key not in self._adapters:
            raise ProfileNotFoundError(
                f"profile {profile.profile_id!r} names adapter_key "
                f"{profile.adapter_key!r}, which is not registered"
            )
        self._profiles[profile.profile_id] = profile

    def adapter(self, key: str) -> MotionAdapter:
        try:
            return self._adapters[key]
        except KeyError as exc:
            raise ProfileNotFoundError(
                f"unknown adapter_key {key!r}; registered: {sorted(self._adapters)}"
            ) from exc

    def profile(self, profile_id: str) -> EngineProfile:
        try:
            return self._profiles[profile_id]
        except KeyError as exc:
            raise ProfileNotFoundError(
                f"unknown engine profile {profile_id!r}; registered: {self.profile_ids()}"
            ) from exc

    def adapter_for(self, profile: EngineProfile) -> MotionAdapter:
        return self.adapter(profile.adapter_key)

    def profile_ids(self) -> list[str]:
        return sorted(self._profiles)

    def profiles(self) -> list[EngineProfile]:
        return [self._profiles[pid] for pid in self.profile_ids()]


def default_registry() -> Registry:
    """The adapters and profiles this build implements.

    ``animalite render`` requires an explicit ``--profile`` and there is no
    default, so a fixture render can never be mistaken for the learned model and
    vice versa. Registering the RIFE profile does not imply its runtime is
    installed: validation reports an unverified or missing runtime as an
    actionable error rather than failing at execution time.
    """
    registry = Registry()
    registry.register_adapter(FixtureAdapter())
    registry.register_profile(FIXTURE_PROFILE)
    registry.register_adapter(RifeNcnnAdapter())
    registry.register_profile(RIFE_PROFILE)
    return registry
