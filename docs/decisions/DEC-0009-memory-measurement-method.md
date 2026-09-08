# DEC-0009 — Peak memory measurement method

* **Status:** Accepted
* **Deciding role:** implementation
* **Affects:** §12.0 application memory, MR-013, NFR-028, handoff v0.2 rule 6

## Decision

Peak memory is sampled by the best method available, and the method, scope and
caveats are recorded with every observation:

| Priority | Method | Scope | Sufficient for §12.0? |
| --- | --- | --- | --- |
| 1 | cgroup `memory.peak` (v2) or `memory.max_usage_in_bytes` (v1) | every process in the cgroup — app, worker and encoder | Yes |
| 2 | `/proc/self/status:VmHWM` + `getrusage(RUSAGE_CHILDREN).ru_maxrss` | parent high-water mark plus the largest reaped child peak | **No** |
| 3 | none available | — | No; recorded as `unavailable` |

Method 2 records these caveats on the observation itself:

* the two peaks may not have occurred simultaneously, so this is not a true
  process-group simultaneous peak;
* it is **not** sufficient evidence for the §12.0 "≤ 4 GiB across the app,
  temporal worker and encoder" condition.

The evaluator enforces that: a run measured with method 2 draws a blocking
`OBS-MEMORY-SCOPE` finding, and a run with no measured observation draws
`OBS-MEMORY-MISSING`.

## Why not psutil

An extra runtime dependency to read `/proc` was not justified, and the important
work here is not reading the number — it is being explicit about what the number
covers. The layered approach makes the scope difference visible in the data
rather than hidden behind a uniform-looking API.

## The zero-as-success rule

`MemoryObservation` refuses to carry `peak_bytes` unless `status` is `measured`,
and refuses `measured` with no value. A platform with no counter therefore
produces `{"status": "unavailable", "peak_bytes": null}` — never
`{"peak_bytes": 0}`, which would read as a suspiciously excellent result.

## Known limitation on the current development host

The cgroup counter reports an absolute high-water mark for the whole cgroup,
including processes unrelated to the render, and the baseline at run start is
recorded but not subtracted. The observation says so in its `caveats`. On the
D-02-approved P-L host the render should be the only workload (§12.0 requires no
competing workload), which is what makes the reading attributable there.
