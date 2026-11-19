"""Aggregation for benchmark observations.

Section 12.0: "median and nearest-rank p95 (sorted index ceil(0.95 x n))".
With one-based indexing that makes n=36 select the 35th sorted observation and
n=12 select the maximum -- both are covered by tests.

Two rules that keep the numbers honest:

* an empty sample has no statistics; the functions return ``None`` rather than
  0.0, so a missing distribution cannot render as a fast one;
* only *successful* runs carry an observation. Filtering failures out of the
  input list is the caller's job, and the evaluator separately refuses a pass
  when any planned run did not succeed -- so a small surviving sample can never
  become a passing score (section 12.0: "Do not calculate a passing score from
  only successful runs").
"""

from __future__ import annotations

import math
from collections.abc import Sequence

__all__ = ["maximum", "median", "nearest_rank_index", "nearest_rank_percentile", "summarize"]


def nearest_rank_index(n: int, percentile: float = 0.95) -> int:
    """One-based sorted index for the nearest-rank percentile.

    ``ceil(percentile * n)``, clamped to ``1..n``. For n=36, p95 -> 35.
    For n=12, p95 -> 12 (the maximum).
    """
    if n <= 0:
        raise ValueError("nearest_rank_index requires n >= 1")
    if not 0.0 < percentile <= 1.0:
        raise ValueError(f"percentile must be in (0, 1]; got {percentile}")
    return max(1, min(n, math.ceil(percentile * n)))


def nearest_rank_percentile(
    values: Sequence[float], percentile: float = 0.95
) -> tuple[float, int] | None:
    """Return ``(value, one_based_index)`` or ``None`` for an empty sample."""
    if not values:
        return None
    ordered = sorted(values)
    index = nearest_rank_index(len(ordered), percentile)
    return ordered[index - 1], index


def median(values: Sequence[float]) -> float | None:
    """Conventional median: the middle value, or the mean of the two middle values."""
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def maximum(values: Sequence[float]) -> float | None:
    return max(values) if values else None


def summarize(values: Sequence[float], percentile: float = 0.95) -> dict[str, float | int | None]:
    """Median / percentile / max / min for a sample, all ``None`` when empty."""
    percentile_result = nearest_rank_percentile(values, percentile)
    return {
        "n": len(values),
        "median": median(values),
        "percentile": percentile_result[0] if percentile_result else None,
        "percentile_sorted_index": percentile_result[1] if percentile_result else None,
        "maximum": maximum(values),
        "minimum": min(values) if values else None,
    }
