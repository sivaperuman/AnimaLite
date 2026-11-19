"""Shot intent: the Package A subset of the section 10.2 shot manifest.

Only the identity, timing, format, creative, keyframe and routing groups are
modelled here. The layers, controls, audio, rights_inputs, rights and review
groups belong to later work packages and are deliberately absent rather than
stubbed with placeholder values.
"""

from __future__ import annotations

from pydantic import Field

from animalite.contracts.base import Document
from animalite.contracts.enums import EndpointControlMode, MotionTier

__all__ = ["ShotIntent"]


class ShotIntent(Document):
    shot_code: str = Field(min_length=1)
    revision: int = Field(default=1, ge=1)
    project_id: str | None = None
    episode_id: str | None = None
    sequence_id: str | None = None

    target_duration_seconds: float = Field(gt=0)
    timeline_role: str = "tier_eligible_content"
    tier_share_eligible: bool = True

    motion_description: str = ""
    camera: str = ""
    negative_constraints: list[str] = Field(
        default_factory=lambda: ["photorealism", "text", "captions", "watermark"]
    )

    assigned_tier: MotionTier = MotionTier.E3
    tier_justification: str = ""
    endpoint_control_mode: EndpointControlMode = EndpointControlMode.DETERMINISTIC_STATE
    endpoint_control_scope: str = "both"

    reference_pack_version: str | None = None
