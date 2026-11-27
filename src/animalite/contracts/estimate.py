"""ResourceEstimate contract (section 6.3, CR-006, MR-013).

An estimate is a *prediction*, not an observation. The two are separate types
and are never merged: :class:`ResourceEstimate` carries ``kind="estimate"`` and
:mod:`animalite.contracts.results` carries ``kind="observation"``.

CR-006 requires the estimate to stay device-class agnostic: accelerator type,
memory and minutes are optional fields, not required contract fields.
"""

from __future__ import annotations

from pydantic import Field

from animalite.contracts.base import Contract, Document

__all__ = ["ResourceEstimate", "ReusableSetupUnit"]


class ReusableSetupUnit(Contract):
    """One typed unit of reusable/shared setup cost (section 6.3, CR-003)."""

    unit_kind: str = Field(min_length=1)
    unit_count: int = Field(ge=0)
    artist_hours_per_unit: float = Field(ge=0.0)
    accelerator_minutes_per_unit: float = Field(default=0.0, ge=0.0)


class ResourceEstimate(Document):
    """Device-class-agnostic estimate returned by ``estimate(job)``.

    Reusable setup, incremental per-shot setup and marginal render are kept as
    three separate groups so a shared setup cost can be counted once and never
    folded into per-shot render time.
    """

    kind: str = "estimate"
    profile_id: str
    request_id: str | None = None

    # --- reusable / shared setup (counted once, amortized only under CR-003) ---
    reusable_setup_units: list[ReusableSetupUnit] = Field(default_factory=list)
    reusable_integration_overhead_hours: float = Field(default=0.0, ge=0.0)

    # --- incremental per-shot setup ---
    preparation_active_seconds: float = Field(ge=0.0)
    preparation_wall_seconds: float = Field(ge=0.0)

    # --- marginal render ---
    cold_start_seconds: float = Field(ge=0.0)
    preview_wall_seconds: float = Field(ge=0.0)
    render_encode_wall_seconds: float = Field(ge=0.0)

    # --- output shape ---
    input_anchor_count: int = Field(ge=0)
    animation_frame_count: int = Field(ge=0)
    delivery_frame_count: int = Field(ge=0)

    # --- resources ---
    peak_application_memory_bytes: int = Field(ge=0)
    thread_count: int = Field(ge=1)
    scratch_storage_mb: float = Field(ge=0.0)

    estimated_cost: float | None = None
    accelerator_type: str | None = None
    accelerator_memory_bytes: int | None = None
    accelerator_minutes: float | None = None

    basis: str = Field(
        default="",
        description="How the estimate was derived; an unmeasured heuristic must say so.",
    )
    is_measured: bool = False
