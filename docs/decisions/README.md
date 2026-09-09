# Implementation decision log

One file per durable decision. A decision recorded here is **settled for the
active scope**: do not reopen it or ask for confirmation again unless new
evidence, a requirement change, or an owner decision supersedes it
(handoff v0.2 section 7).

Each record states: the decision, who made it, why, the requirements it touches,
alternatives considered, and how it would be reversed. `Deciding role` uses:

* **implementation** — a routine, reversible engineering choice inside the
  approved scope, resolved by Claude Code and recorded here rather than escalated;
* **review** — a technical decision recorded by ChatGPT in a PR comment;
* **owner** — scope, target, hardware, spend or rights. Never taken by an agent.

`Comment URL` is filled in once the decision is confirmed or amended in PR review.

| ID | Decision | Deciding role | Status | Affects |
| --- | --- | --- | --- | --- |
| [DEC-0001](DEC-0001-licensing-baseline.md) | PolyForm Noncommercial 1.0.0 for AnimaLite's own code; source-available wording | implementation (recommendation) / **owner** (adoption) | Proposed — needs owner confirmation | §0 handoff, C-04, MR-012 |
| [DEC-0002](DEC-0002-python-and-tooling.md) | CPython 3.11 baseline; pydantic + numpy runtime deps; Ruff / mypy / pytest; constraints-file lock | implementation | Accepted | §6.2, handoff §2 |
| [DEC-0003](DEC-0003-contract-and-schema-style.md) | Pydantic v2 contracts, `extra="forbid"`, canonical-JSON digests, `EvidenceStatus` for absent observations | implementation | Accepted | §10, handoff rule 2 |
| [DEC-0004](DEC-0004-media-and-encoder-settings.md) | External FFmpeg, pinned H.264/High/yuv420p settings, streaming encode, decode-validate before publish | implementation | Accepted | §12.0 core output, NFR-019, handoff rules 5 & 7 |
| [DEC-0005](DEC-0005-preview-cadence.md) | Preview uses the project cadence policy: 36 animation frames at 12 fps → 72 delivery frames at 24 fps = 3.000 s | implementation | Accepted (measurement clarification) | §12.0 warm preview, CR-004, D-09 |
| [DEC-0006](DEC-0006-preview-repetitions.md) | 36 independent warm preview requests, three per locked clip, in addition to the final-output runs | implementation (from handoff §5) | Accepted (measurement clarification) | §12.0 sample & pass calculation |
| [DEC-0007](DEC-0007-percentile-and-median.md) | Nearest-rank p95 at `ceil(0.95 × n)` one-based; conventional median; empty sample yields `null`, never 0 | implementation | Accepted | §12.0 aggregation |
| [DEC-0008](DEC-0008-fixture-adapter-boundary.md) | The fixture adapter is deterministic, labelled non-learned, and structurally barred from qualifying | implementation | Accepted | MR-018, AT-055/056, handoff §13 |
| [DEC-0009](DEC-0009-memory-measurement-method.md) | Prefer cgroup peak; fall back to VmHWM + child maxrss with disclosed caveats; never report an absent measurement as zero | implementation | Accepted | §12.0 application memory, MR-013, handoff rule 6 |
| [DEC-0014](DEC-0014-review-dispositions-pr1.md) | PR-1 consolidated review: R1–R6 fixes, the non-overridable qualification gate, CI policy and Package B boundaries | review | Accepted and implemented | §12.0, NFR-028, AT-055/056, handoff §8 |
| [DEC-0010](DEC-0010-ledger-integrity.md) | Declared run plan plus an append-only hash-chained ledger; deletion, edit or reorder is detected and blocks qualification | implementation | Accepted | §12.0 failure handling, NFR-003 |
| [DEC-0011](DEC-0011-rife-model-selection.md) | Pin `rife-v4.6`; exclude `rife-anime`; reject midpoint-only models at non-0.5 timesteps | implementation | Accepted | MR-018, MR-016, §9.1 |
| [DEC-0012](DEC-0012-rife-invocation-strategy.md) | Per-frame `-s` invocation for correct frame indexing; model-load cost counted, persistent worker deferred with a measured trigger | implementation | Accepted | §12.0 boundary/semantics, CR-004, NFR-028 |
| [DEC-0013](DEC-0013-rife-licence-position.md) | RIFE code and weights are MIT upstream; the conversion chain stays `pending`/`use_eligible=false` until reviewed | implementation (evidence) / **owner + legal** (disposition) | Unresolved — blocks qualification, not development | C-04, MR-012, MR-014, CR-024, D-06 |
| [DEC-0015](DEC-0015-classical-comparator.md) | The classical warp/flow comparator is block matching in NumPy, in-repo, not `minterpolate`; it exists to be beaten and cannot qualify | implementation | Accepted | §6.0, MR-018, MR-016, AT-055/056 |
