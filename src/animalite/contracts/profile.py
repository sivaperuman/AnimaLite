"""Engine profile and capability contracts (MR-007, MR-013, MR-016, section 6.3)."""

from __future__ import annotations

from pydantic import Field, model_validator

from animalite.contracts.assets import MAX_ANCHORS, MIN_ANCHORS
from animalite.contracts.base import Contract, Document
from animalite.contracts.enums import EndpointControlMode, EngineClass, MotionTier

__all__ = [
    "ArtifactIdentity",
    "Capabilities",
    "EngineProfile",
    "LicenseEvaluationRef",
    "Resolution",
    "ThreadBudget",
]


class Resolution(Contract):
    width: int = Field(ge=16)
    height: int = Field(ge=16)

    def as_tuple(self) -> tuple[int, int]:
        return (self.width, self.height)


class ThreadBudget(Contract):
    """Explicit thread budget across Python, native inference and the encoder.

    Handoff section 2 (Parallelism): "explicitly budget threads across Python,
    native inference and the encoder". The sum must not exceed ``total_threads``
    so a profile cannot quietly oversubscribe the 4-core P-L host.
    """

    total_threads: int = Field(ge=1, le=256)
    python_threads: int = Field(default=1, ge=1)
    inference_threads: int = Field(default=1, ge=0)
    encoder_threads: int = Field(default=1, ge=0)

    @model_validator(mode="after")
    def _check_budget(self) -> ThreadBudget:
        allocated = self.python_threads + self.inference_threads + self.encoder_threads
        if allocated > self.total_threads:
            raise ValueError(
                f"thread budget over-allocated: python={self.python_threads} + "
                f"inference={self.inference_threads} + encoder={self.encoder_threads} "
                f"= {allocated} > total_threads={self.total_threads}"
            )
        return self


class ArtifactIdentity(Contract):
    """Identity of a pinned binary or weight file (handoff rule 7 and 8).

    ``content_hash`` is optional only so a profile can *declare* an artifact it
    has not yet verified; :mod:`animalite.core.validation` rejects execution
    when a declared artifact is unverified.
    """

    kind: str
    identifier: str
    version: str | None = None
    content_hash: str | None = None
    source_url: str | None = None
    license_id: str | None = None
    notes: str | None = None


class LicenseEvaluationRef(Contract):
    """Pointer to a section 14.2 license evaluation. Package A records, not decides."""

    evaluation_id: str
    subject: str
    policy_state: str = "pending"
    use_eligible: bool = False
    eligibility_block_kind: str = "resolvable"
    reviewer: str | None = None
    evidence_url: str | None = None


class EngineProfile(Document):
    """A versioned, output-affecting engine configuration.

    ``learned_temporal_participation`` and ``qualification_eligible`` are the
    two fields that keep the MR-018 claim honest. A profile whose learned
    component does not participate in temporal synthesis can never be marked
    qualification-eligible, and the model validator enforces that.
    """

    profile_id: str = Field(min_length=1)
    display_name: str
    revision: int = Field(default=1, ge=1)
    adapter_key: str = Field(min_length=1)

    engine_class: EngineClass
    learned_temporal_participation: bool
    qualification_eligible: bool
    non_qualifying_reason: str | None = None

    supported_tiers: list[MotionTier] = Field(min_length=1)
    supported_tasks: list[str] = Field(min_length=1)
    supported_controls: list[str] = Field(default_factory=list)
    supported_endpoint_modes: list[EndpointControlMode] = Field(min_length=1)
    supported_resolutions: list[Resolution] = Field(min_length=1)
    min_anchor_count: int = Field(default=MIN_ANCHORS, ge=1)
    max_anchor_count: int = Field(default=MAX_ANCHORS, ge=1)
    max_animation_frame_count: int = Field(default=72, ge=2)

    cpu_only_guaranteed: bool = True
    thread_budget: ThreadBudget
    parameters: dict[str, float | int | str | bool] = Field(default_factory=dict)

    weights: list[ArtifactIdentity] = Field(default_factory=list)
    binaries: list[ArtifactIdentity] = Field(default_factory=list)
    license_evaluation: LicenseEvaluationRef | None = None

    @model_validator(mode="after")
    def _check_qualification_claim(self) -> EngineProfile:
        if self.max_anchor_count < self.min_anchor_count:
            raise ValueError(
                f"max_anchor_count ({self.max_anchor_count}) < min_anchor_count "
                f"({self.min_anchor_count})"
            )
        if self.qualification_eligible and not self.learned_temporal_participation:
            raise ValueError(
                f"profile {self.profile_id!r} claims qualification_eligible=True but "
                "learned_temporal_participation=False; MR-018 requires the learned "
                "component to participate in temporal synthesis"
            )
        if self.qualification_eligible and self.engine_class is EngineClass.DETERMINISTIC:
            raise ValueError(
                f"profile {self.profile_id!r} declares engine_class 'deterministic' and "
                "cannot be qualification_eligible under MR-018"
            )
        if not self.qualification_eligible and not self.non_qualifying_reason:
            raise ValueError(
                f"profile {self.profile_id!r} is not qualification_eligible and must "
                "state non_qualifying_reason so reports can label it"
            )
        return self

    def supports_resolution(self, width: int, height: int) -> bool:
        return any(r.as_tuple() == (width, height) for r in self.supported_resolutions)


class Capabilities(Document):
    """Result of ``capabilities(engine_profile)`` in the section 6.3 contract."""

    profile_id: str
    adapter_key: str
    engine_class: EngineClass
    learned_temporal_participation: bool
    qualification_eligible: bool
    non_qualifying_reason: str | None = None
    supported_tiers: list[MotionTier]
    supported_tasks: list[str]
    supported_controls: list[str]
    supported_endpoint_modes: list[EndpointControlMode]
    supported_resolutions: list[Resolution]
    min_anchor_count: int
    max_anchor_count: int
    max_animation_frame_count: int
    cpu_only_guaranteed: bool
    supports_safe_cancel: bool
    notes: list[str] = Field(default_factory=list)
