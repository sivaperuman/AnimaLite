"""Host and environment inventory contracts.

Handoff section 13, item 5: "Treat it as inventory, not owner approval or proof
that an accelerated device was unused." :class:`HostApproval` therefore defaults
to *not approved* and can only be populated from an explicit D-02 record.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from animalite.contracts.base import Document
from animalite.contracts.enums import EvidenceStatus, MemoryMethod

__all__ = ["HostApproval", "HostInventory", "ToolIdentity"]


class ToolIdentity(Document):
    """Identity of an external executable actually resolved on this host."""

    name: str
    available: bool
    path: str | None = None
    version: str | None = None
    build_configuration: str | None = None
    license_relevant_flags: list[str] = Field(default_factory=list)
    content_hash: str | None = None
    error: str | None = None


class HostApproval(Document):
    """D-02 approval status for the host. Never inferred from hardware alone."""

    approved: bool = False
    decision_id: str | None = None
    decision_url: str | None = None
    approved_by: str | None = None
    approved_at: str | None = None
    notes: str = (
        "Core count alone is not hardware equivalence (D-02). An unapproved host "
        "produces exploratory observations only."
    )

    @model_validator(mode="after")
    def _check(self) -> HostApproval:
        if self.approved and not (self.decision_id and self.approved_by):
            raise ValueError(
                "approved=True requires decision_id and approved_by; a host cannot approve itself"
            )
        return self


class HostInventory(Document):
    """Recorded host facts. Unknown values stay ``None``, never zero."""

    collected_at: str
    hostname_recorded: bool = False

    os_name: str
    os_release: str
    os_version: str | None = None
    kernel: str | None = None
    architecture: str
    libc: str | None = None

    cpu_model: str | None = None
    physical_cores: int | None = Field(default=None, ge=1)
    logical_cores: int | None = Field(default=None, ge=1)
    cpu_flags_recorded: list[str] = Field(default_factory=list)
    cpu_max_mhz: float | None = None

    total_ram_bytes: int | None = Field(default=None, ge=0)
    cgroup_memory_max_bytes: int | None = Field(default=None, ge=0)
    swap_total_bytes: int | None = Field(default=None, ge=0)

    python_version: str
    python_implementation: str
    python_executable: str

    thread_environment: dict[str, str] = Field(default_factory=dict)
    tools: list[ToolIdentity] = Field(default_factory=list)

    memory_measurement_method: MemoryMethod = MemoryMethod.NONE
    memory_measurement_status: EvidenceStatus = EvidenceStatus.UNAVAILABLE
    memory_measurement_scope: str = "unknown"

    accelerator_probe_status: EvidenceStatus = EvidenceStatus.PENDING
    accelerator_probe_notes: list[str] = Field(default_factory=list)

    approval: HostApproval = HostApproval()

    virtualization_hints: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def tool(self, name: str) -> ToolIdentity | None:
        return next((t for t in self.tools if t.name == name), None)
