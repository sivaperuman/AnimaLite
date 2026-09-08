# DEC-0014 — Review dispositions from the PR-1 consolidated review

* **Status:** Accepted and implemented
* **Deciding role:** review (ChatGPT/reviewer), recorded by implementation
* **Comment URL:** https://github.com/sivaperuman/AnimaLite/pull/1#issuecomment-5584684419
* **Reviewed head:** `0e2c1a98dc4c190bc70b8ce9c281f34abd929375`

## Findings accepted and fixed

All six findings were **independently reproduced before being fixed**. Each was
real; none was a misreading of the code.

| ID | Reproduced as | Disposition |
| --- | --- | --- |
| R1 | A plan declaring 3 warm repetitions while scheduling 1, and records carrying a different profile/host/plan with `exploratory=true`, both reached `qualifying_pass` with **zero** blocking findings | Fixed: real schedule validation, record↔plan identity binding, dataset/profile/target/host digest binding, plus a non-overridable implementation gate |
| R2 | A 20-minute workload that breached **both** latency and memory with a 9 GiB peak reached `qualifying_pass`; four copies of one fresh pack satisfied the four-pack rule | Fixed: workload outcomes, memory scope/limit, thermal status and swap evidence all checked; fresh packs must be four *distinct* ids |
| R3 | Cold runs reconstructed the service in the same interpreter, reusing the same `Registry` and adapter instance | Fixed: each cold run launches a fresh interpreter inside the clock and records process evidence |
| R4 | A 0.2 s deadline against a non-reading child returned after **3.06 s**, classified as an encoder error | Fixed: deadline-bounded non-blocking writes; anchor decode bound to the job deadline; group-aware teardown |
| R5 | Two renders with different controls produced different settings digests and a **byte-identical** output | Fixed: effective controls resolved once and passed to synthesis |
| R6 | `fatal: bad object <head sha>` in the scope step; the selector always fell through to full CI | Fixed: full history fetched, diff against the merge commit, executables under `docs/` never exempted |

## The qualification implementation gate (R1)

`bench/evaluate.py` now carries `QUALIFICATION_IMPLEMENTATION_GAPS`, a module
constant listing bindings a formal pass requires but which do not exist yet.
While it is non-empty the evaluator returns `NOT_ELIGIBLE` for **every** input.

It is a module constant deliberately: no argument, profile field or evidence
bundle can lift it, so a caller cannot talk the evaluator into a pass the
implementation cannot substantiate. Diagnostics are still reported normally.
Package B/C remove entries; the gate disappears when the list empties, at which
point the control test flips to `QUALIFYING_PASS` and every other evaluator test
keeps its meaning.

## Reviewer dispositions on the open PR-body questions

| Question | Disposition |
| --- | --- |
| Memory fallback: blocking or warning? | **Blocking for qualification.** Parent VmHWM + largest child RSS is diagnostic, not a simultaneous group peak. Still displayed for development. |
| Median and percentile | **Accepted** as implemented (DEC-0007). |
| Preview cadence and repetitions | **Accepted** (DEC-0005, DEC-0006). |
| Warm boundary and output hashing | **Accepted**: decode, synthesis, conversion, encode, validation, publication and required output hashing stay inside end-to-end latency. Repeated native model loads are **not** excluded. |
| Process-cold and timeout limits | **Amended** — see R3 and R4. |
| `ShotIntent` subset | **Accepted** as a CPU-stage subset; broader §10.2 groups marked deferred, not claimed. |
| Dependency constraints | **Accepted** as a development baseline, with an explicit note that commented hashes are **not enforced by pip**. Binary/weight checksums are enforced in Package B. |
| Ledger tamper evidence | **Accepted** for this stage, after R1's identity checks. Tamper evidence relative to a published reference, not a signed attestation. |
| Licensing baseline / copyright holder | Retain PolyForm Noncommercial 1.0.0 and source-available wording. LIC-01 remains owner metadata; not invented. |
| 720p / real-time factor | 720p deferred. RTF is derived from measured duration, not a separate escape hatch. |

## CI policy decided for this stage (R6)

1. One `pull_request` lane (`opened`, `synchronize`, `reopened`,
   `ready_for_review`); the duplicate `push: main` full suite is removed.
2. Draft PRs skip the runner work but keep one truthful required check;
   `ready_for_review` triggers the real checks.
3. Scope detection runs **before** Python setup, so a documentation-only PR
   installs nothing. Documentation means prose only — an executable or manifest
   under `docs/` is still code.
4. Read-only permissions, SHA-pinned actions, finite timeout, concurrency
   cancellation, one Python/OS lane, caching, preinstalled FFmpeg when present.
5. Batch commits locally, run the local gate once, push one reviewable batch.
   No schedules, dispatches or bots that rerun CI automatically. `[skip ci]` is
   not the mechanism, since skipped required workflows leave checks pending.

## Package B boundaries approved

B-1 (separate branch and PR), B-2 (explicit `runtime fetch`/`status` provisioning
with verified digests), B-3 (per-frame `-s`; persistent worker only after a
measured bottleneck), B-4 (RIFE v4.6 as the single initial candidate) and B-5
(record the licence uncertainty; `pending`/`use_eligible=false` preserved) are
all approved as proposed. Recorded in DEC-0011, DEC-0012 and DEC-0013.

The reviewer additionally noted that the disc-based test is useful against
cross-fading but **a classical motion algorithm could also pass it**, so it must
be paired with verified runtime/weight identity and observed learned inference
rather than used alone to certify MR-018. Carried into Package B.
