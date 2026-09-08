"""Observation contracts: stage timings, memory evidence, output manifest.

Every type here records something that was *measured*. The evidence-status
fields exist so an absent observation stays absent: a memory observation with
``status != measured`` has ``peak_bytes = None``, never ``0``.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from animalite.contracts.base import Contract, Document
from animalite.contracts.enums import EvidenceStatus, MemoryMethod, Stage
from animalite.contracts.media import FrameAccounting

__all__ = [
    "DecodeProbe",
    "DeviceEvidence",
    "MemoryObservation",
    "OutputManifest",
    "StageTiming",
]


class StageTiming(Contract):
    """Wall time for one execution stage, in seconds.

    ``inside_timing_boundary`` records whether the stage counts toward the
    section 12.0 warm boundary. Only model/runtime residency may sit outside it.
    """

    stage: Stage
    wall_seconds: float = Field(ge=0.0)
    inside_timing_boundary: bool = True
    detail: str | None = None


class MemoryObservation(Contract):
    """Peak memory evidence with its method and honest scope.

    Handoff rule 6: "Record the combined app/worker/encoder memory method;
    measuring only the Python parent is insufficient." When only the parent can
    be measured, ``scope`` says so and ``caveats`` records why.
    """

    status: EvidenceStatus
    method: MemoryMethod = MemoryMethod.NONE
    peak_bytes: int | None = Field(default=None, ge=0)
    scope: str = "unknown"
    caveats: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_status(self) -> MemoryObservation:
        if self.status is EvidenceStatus.MEASURED:
            if self.peak_bytes is None:
                raise ValueError("status 'measured' requires peak_bytes")
            if self.method is MemoryMethod.NONE:
                raise ValueError("status 'measured' requires a memory method")
        elif self.peak_bytes is not None:
            raise ValueError(
                f"status {self.status.value!r} must not carry peak_bytes; an "
                "unavailable observation is not a zero measurement"
            )
        return self

    @classmethod
    def unavailable(cls, reason: str) -> MemoryObservation:
        return cls(status=EvidenceStatus.UNAVAILABLE, caveats=[reason])


class DeviceEvidence(Contract):
    """Evidence that execution stayed on the CPU (MR-015, NFR-028, handoff rule 7).

    Package A executes no inference runtime, so ``inference_device`` is
    ``not_applicable`` rather than a claimed CPU-only proof.
    """

    inference_device_status: EvidenceStatus = EvidenceStatus.NOT_APPLICABLE
    inference_device: str | None = None
    encoder_device: str = "cpu"
    hardware_acceleration_requested: bool = False
    network_calls_observed_status: EvidenceStatus = EvidenceStatus.PENDING
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> DeviceEvidence:
        if self.inference_device_status is EvidenceStatus.MEASURED and not self.inference_device:
            raise ValueError("status 'measured' requires an inference_device value")
        return self


class DecodeProbe(Contract):
    """What the decoder actually reported about the published file."""

    container_format: str
    codec: str
    profile: str | None = None
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    pixel_format: str
    counted_frames: int = Field(ge=0)
    avg_frame_rate: str
    duration_seconds: float = Field(ge=0.0)
    size_bytes: int = Field(ge=0)


class OutputManifest(Document):
    """The published output. Only written after encode close *and* decode probe."""

    path: str
    content_hash: str
    frame_accounting: FrameAccounting
    probe: DecodeProbe
    settings_digest: str
    is_qualifying_evidence: bool = False
    non_qualifying_reason: str | None = None

    @model_validator(mode="after")
    def _check_label(self) -> OutputManifest:
        if not self.is_qualifying_evidence and not self.non_qualifying_reason:
            raise ValueError("non-qualifying output must carry non_qualifying_reason")
        return self
