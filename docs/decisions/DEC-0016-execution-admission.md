# DEC-0016 — Executing third-party model artifacts requires recorded admission

* **Status:** Accepted
* **Deciding role:** implementation (the mechanism) — the *decisions it records*
  are owner/legal, and this deliberately cannot make one
* **Affects:** CR-024, C-04, MR-012, MR-014, D-06, DEC-0013
* **Raised by:** PR-2 review, finding B-R1

## Decision

A profile whose `learned_temporal_participation` is true may not be executed
unless an **approved admission record** covers every artifact digest it declares
**and** the purpose the run declares. Missing, pending and rejected all block,
and they block **before any native invocation** — in validation, and again in
the adapter for a caller that bypassed validation.

Artifact *verification* and execution *admission* stay separate mechanisms.

## Why this was necessary

Package B verified digests and warned about the licence position. It did not
stop anything. Reproduced in review with a hash-verified runtime: the pending,
`use_eligible=false` profile produced **zero validation errors**, and removing
the licence evaluation entirely also produced zero errors. The warning's own
remediation said development and benchmarking "may proceed".

The gate that did exist was in the benchmark evaluator. That is not enforcement:
refusing to *count* a run that has already downloaded weights, executed the
runtime and produced frames does not prevent the use whose terms are unresolved.

## What a record is

`animalite.contracts.admission.ExecutionAdmission`, one JSON file per decision,
read from `ANIMALITE_ADMISSION_DIR` or `$XDG_DATA_HOME/animalite/admissions`.

An `approved` record is refused by the schema unless it names its `reviewer`,
its `reference`, its `recorded_at`, at least one `permitted_purpose` and at
least one `artifact_hash`. An approval with those blank is the shape a bypass
would take, so the contract does not accept one.

Purposes are separate permissions: `research`, `benchmark`, `production`,
`redistribution`. A record clearing local research does not clear benchmark
evidence, and `RenderRequest.execution_purpose` makes each run declare which it
is (the benchmark runner declares `benchmark`).

Coverage is by digest. Adding or changing an artifact invalidates the record
rather than inheriting it — which is the property that makes "approved for these
weights" mean something.

## Three deliberate choices

**No development bypass flag.** Not an environment variable, not a `--force`,
not a `waived` decision value. A bypass would be used, and then the enforcement
would be decorative. Development on the learned path happens against the stub
runtime in the tests, which executes no third-party artifact.

**Records live outside the repository.** An approval is an operator's decision
about their own use; committing one would make every checkout inherit it. What
*is* committed is the dossier — `docs/licensing/admissions/rife-ncnn-20221029.json`,
carrying `decision: pending` — which lists the exact artifacts, the open
questions and the purposes being requested, and is what a reviewer signs. A test
asserts nothing committed there is ever `approved`.

**An unreadable record blocks.** Skipping a malformed file would silently turn a
malformed *rejection* into no rejection at all.

## Consequences, including an uncomfortable one

`animalite render --profile rife-ncnn-v4.6-cpu` **now fails on a fresh
checkout**, and the model tests report pending rather than running. That is the
intended behaviour and AGENTS.md says so at the command. It is uncomfortable
because it means the project's own learned path is blocked by its own rights
position — which is exactly the position DEC-0013 records, now enforced instead
of noted.

Runtime-dependent tests additionally require `ANIMALITE_RUN_MODEL_TESTS=1`:
having the runtime installed is not consent to execute it.

## Reversal

If the D-06 reviewer records an approval, an operator copies the dossier into
the admission directory and fills in the required fields; nothing in the code
changes. If the review concludes the artifacts may not be used, `rejected` is
recorded the same way and the block becomes permanent rather than pending.

The mechanism itself would only be removed if the project stopped executing
third-party artifacts altogether.
