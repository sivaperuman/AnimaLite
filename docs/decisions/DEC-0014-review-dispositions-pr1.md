# DEC-0014 — Review dispositions from the PR-1 consolidated review

* **Status:** Accepted and implemented
* **Deciding role:** review (ChatGPT/reviewer), recorded by implementation
* **Comment URL:** https://github.com/sivaperuman/AnimaLite/pull/1#issuecomment-5584975300
  (the consolidated review that made these decisions; comment `5584684419` is
  the earlier implementation investigation it responded to, not the decision.)
* **Follow-up review:** https://github.com/sivaperuman/AnimaLite/pull/1#issuecomment-5585335911
  — accepted R1/R2/R6 for the gated foundation and returned R3/R4/R5 as partial.
* **Reviewed head:** `0e2c1a98dc4c190bc70b8ce9c281f34abd929375`; follow-up
  reviewed `8ba39f5d0a9e1666f6a4f7c7b7f8e002f57b7c50`.

## Findings accepted and fixed

All six findings were **independently reproduced before being fixed**. Each was
real; none was a misreading of the code.

| ID | Reproduced as | Disposition |
| --- | --- | --- |
| R1 | A plan declaring 3 warm repetitions while scheduling 1, and records carrying a different profile/host/plan with `exploratory=true`, both reached `qualifying_pass` with **zero** blocking findings | Fixed: real schedule validation, record↔plan identity binding, dataset/profile/target/host digest binding, plus a non-overridable implementation gate |
| R2 | A 20-minute workload that breached **both** latency and memory with a 9 GiB peak reached `qualifying_pass`; four copies of one fresh pack satisfied the four-pack rule | Fixed: workload outcomes, memory scope/limit, thermal status and swap evidence all checked; fresh packs must be four *distinct* ids |
| R3 | Cold runs reconstructed the service in the same interpreter, reusing the same `Registry` and adapter instance | **Partial, then completed** — see the second round below |
| R4 | A 0.2 s deadline against a non-reading child returned after **3.06 s**, classified as an encoder error | **Partial, then completed** — see the second round below |
| R5 | Two renders with different controls produced different settings digests and a **byte-identical** output | **Partial, then completed** — see the second round below |
| R6 | `fatal: bad object <head sha>` in the scope step; the selector always fell through to full CI | Fixed: full history fetched, diff against the merge commit, executables under `docs/` never exempted |

## Second round: R3, R4 and R5 completed

The follow-up review accepted R1, R2 and R6 and returned R3, R4 and R5 as
**partial**. Each remaining defect was reproduced again before being fixed.

| ID | Reproduced as | Disposition |
| --- | --- | --- |
| R3(a) | With an overridden `fixture-synthetic` registered in the parent, the warm run produced `5fb314b0…` and the cold run produced `65057667…` — the *default* profile's output — while both recorded success under the same planned profile | Fixed: the child receives an `ExecutionEnvelope` carrying the resolved profile and its digest; the parent verifies the executed digest before accepting the record |
| R3(b) | `child_pid` was always `null`: `subprocess.CompletedProcess` has no `pid`, so the `hasattr` fallback masked its absence | Fixed: the pid comes from the launched process handle, and the child writes a `(boot_id, pid, start_ticks)` instance marker at startup |
| R3(c) | `test_cold_runs_are_not_faster_than_warm_runs` asserted `min(cold) > min(warm)`, which is not a correctness invariant on a noisy shared runner | Replaced with a controlled-delay proof that the cold clock starts before the launch |
| R3/R4(a) | A child that timed out cleanly wrote a valid failed `AttemptRecord` and exited 1; the parent rejected the exit status before parsing stdout, producing `attempt_id=null`, `category=internal_error` and no diagnostics link | Fixed: the record is parsed first; a record contradicting the process status is refused as a protocol error |
| R3/R4(b) | `subprocess.TimeoutExpired` injected at the cold launch escaped `run_one()` and aborted `run()`, appending **0 of 2** planned runs | Fixed: per-run containment, one launch-to-completion deadline plus a bounded teardown grace, and `run_capture` from the existing process infrastructure instead of `subprocess.run` |
| R4(c) | With a 600 s job deadline and a child that ignored stdin, a cancel at 0.30 s was only observed at **3.010 s**, when the child exited on its own | Fixed: a cancel predicate reaches inside managed writes, waits and supervised captures |
| R5(b) | `controls={"drift_pixels": "not-a-number"}` returned **valid=true with zero errors**, then raised inside synthesis | Fixed: the *resolved* configuration is validated before decode or synthesis |

### Routine policy decisions taken here (DEC-0015 in effect)

* `drift_pixels` accepts a **finite signed** number strictly inside the output
  width. A bool is rejected even though `bool` subclasses `int`: `True` as a
  pixel count is a mistake, not an offset of one.
* A **valid request override replaces an invalid unused default**, because
  synthesis would never have read that default. An invalid default with *no*
  override is an error, attributed to `engine_profile.parameters.<name>` rather
  than to a request control the caller never sent.
* Failure latency is retained in `RunRecord.failure_elapsed_seconds`, kept
  distinct from `wall_seconds` so it can never enter the latency sample.

### Scope of what the digest bindings actually prove

The eligibility checks bind **identifiers and revisions** — dataset digest,
profile digest, target revision, host id — not full host- or target-*content*
digests. A host whose hardware changed under a stable `host_id` would still
match. This is recorded as a limitation, not described as complete binding.

Package B's checks are **not** reviewed or implemented in this PR; its review
remains separate.

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
are all approved as proposed. They are recorded in DEC-0011, DEC-0012 and
DEC-0013, which live on the Package B branch; **none of that work is in this
PR, and none of it has been reviewed here.**

B-5 keeps its restriction as written: the licence uncertainty is recorded and
`policy_state="pending"` with `use_eligible=false` is preserved, which
**blocks execution admission for qualification** until the licence position is
resolved. It is not merely a note that leaves development unaffected.

The reviewer additionally noted that the disc-based test is useful against
cross-fading but **a classical motion algorithm could also pass it**, so it must
be paired with verified runtime/weight identity and observed learned inference
rather than used alone to certify MR-018. Carried into Package B.
