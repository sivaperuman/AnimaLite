# DEC-0007 — Percentile and median definitions

* **Status:** Accepted
* **Deciding role:** implementation
* **Affects:** §12.0 aggregation

## Decision

* **p95 — nearest rank.** Sort ascending; take the observation at one-based index
  `ceil(0.95 × n)`, clamped to `1..n`. This is §12.0's stated rule verbatim.
  n = 36 → index 35. n = 12 → index 12, i.e. the maximum.
* **Median — conventional.** The middle value for odd n; the mean of the two
  middle values for even n.
* **Empty sample → `None`.** Never `0.0`.
* **Reported alongside every distribution:** n planned, n recorded, n succeeded,
  n failed, n missing, the full sorted observation list, median, p95, the p95
  sorted index actually used, maximum and minimum.

## Why the median needed a decision

§12.0 pins the nearest-rank rule for the percentile but says only "median". The
conventional definition (interpolating between the two middle values for even n)
is used, and the p95 index is reported alongside each value so a reader can see
exactly which observation was selected rather than inferring it.

## Why an empty sample returns `None`

A missing distribution rendered as `0.0` would look like an extremely fast one.
Returning `None` forces the report to show absence, and it is the same principle
as `EvidenceStatus` elsewhere in the contracts (DEC-0003).

## Where failures fit

Only successful runs carry a latency observation — the `RunRecord` contract
enforces `wall_seconds is None` for any non-succeeding outcome — so a failed run
cannot contribute a number in either direction.

This is deliberately *not* the same as excusing failures. §12.0 says "Do not
calculate a passing score from only successful runs", and that is enforced
separately: the evaluator emits blocking `OBS-FAILED-RUNS` and `OBS-MISSING-RUNS`
findings, so a sample containing a failure or a missing observation cannot reach
a qualifying pass no matter how good the surviving numbers look.

## Verification

`tests/test_stats.py` covers n = 1, 2, 3, 10, 12, 20, 21, 36, 40, 100 against
`ceil(0.95 × n)`, the two §12.0 sample sizes explicitly, unsorted input, empty
input and invalid percentile arguments.
