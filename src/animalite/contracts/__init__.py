"""Typed, versioned contracts shared by the CLI, execution service and benchmark."""

from __future__ import annotations

from animalite.contracts.assets import AnchorSet, AssetRef, InputAnchor
from animalite.contracts.base import (
    Contract,
    Document,
    canonical_json,
    content_digest,
    sha256_file,
)
from animalite.contracts.enums import (
    CadenceConversion,
    EndpointControlMode,
    EngineClass,
    EvidenceStatus,
    FailureCategory,
    IssueSeverity,
    JobState,
    MemoryMethod,
    MotionTier,
    QualificationVerdict,
    RunKind,
    RunOutcome,
    Stage,
)
from animalite.contracts.estimate import ResourceEstimate, ReusableSetupUnit
from animalite.contracts.host import HostApproval, HostInventory, ToolIdentity
from animalite.contracts.job import (
    AttemptRecord,
    CancelResult,
    EnvironmentRecord,
    FailureRecord,
    JobStatus,
    RenderRequest,
)
from animalite.contracts.media import (
    P_L_FINAL_OUTPUT,
    PREVIEW_OUTPUT,
    CadencePolicy,
    FrameAccounting,
    OutputSpec,
)
from animalite.contracts.profile import (
    ArtifactIdentity,
    Capabilities,
    EngineProfile,
    LicenseEvaluationRef,
    Resolution,
    ThreadBudget,
)
from animalite.contracts.results import (
    DecodeProbe,
    DeviceEvidence,
    MemoryObservation,
    OutputManifest,
    StageTiming,
)
from animalite.contracts.shot import ShotIntent
from animalite.contracts.validation import ValidationIssue, ValidationReport

__all__ = [
    "PREVIEW_OUTPUT",
    "P_L_FINAL_OUTPUT",
    "AnchorSet",
    "ArtifactIdentity",
    "AssetRef",
    "AttemptRecord",
    "CadenceConversion",
    "CadencePolicy",
    "CancelResult",
    "Capabilities",
    "Contract",
    "DecodeProbe",
    "DeviceEvidence",
    "Document",
    "EndpointControlMode",
    "EngineClass",
    "EngineProfile",
    "EnvironmentRecord",
    "EvidenceStatus",
    "FailureCategory",
    "FailureRecord",
    "FrameAccounting",
    "HostApproval",
    "HostInventory",
    "InputAnchor",
    "IssueSeverity",
    "JobState",
    "JobStatus",
    "LicenseEvaluationRef",
    "MemoryMethod",
    "MemoryObservation",
    "MotionTier",
    "OutputManifest",
    "OutputSpec",
    "QualificationVerdict",
    "RenderRequest",
    "Resolution",
    "ResourceEstimate",
    "ReusableSetupUnit",
    "RunKind",
    "RunOutcome",
    "ShotIntent",
    "Stage",
    "StageTiming",
    "ThreadBudget",
    "ToolIdentity",
    "ValidationIssue",
    "ValidationReport",
    "canonical_json",
    "content_digest",
    "sha256_file",
]
