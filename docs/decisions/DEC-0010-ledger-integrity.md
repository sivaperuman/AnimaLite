# DEC-0010 — Benchmark ledger integrity

* **Status:** Accepted
* **Deciding role:** implementation
* **Affects:** §12.0 failure handling and repetitions, NFR-003, NFR-013

## Decision

Every benchmark ledger has two parts:

1. **`plan.json`** — the complete run schedule, written **before any timing
   starts** and refused if one already exists in that directory. Each planned run
   has a stable id (`<clip>:<kind>:<repetition>`) and a recorded order index from
   a seeded shuffle, so the fixed randomized order is replayable.
2. **`runs.jsonl`** — append-only. Each line carries the previous line's digest,
   its own digest over the canonical record, and the record itself.

`RunLedger.verify(plan)` recomputes the chain and compares recorded run ids
against the plan, reporting:

* **missing** run ids — planned but never recorded;
* **unplanned** run ids — recorded but not scheduled;
* **duplicate** records for one run id;
* the exact line where the chain breaks, distinguishing "a record was removed,
  reordered or edited" from "this record was edited after it was written".

Any of these becomes a blocking `LEDGER-INTEGRITY` finding.

## Why

§12.0 requires that a timeout or invalid output "fails the sample and remains in
the ledger", and that retuning means "a new profile revision and complete rerun,
not deletion of weak cases". Both are statements about *what must not be
possible*, so they are enforced mechanically rather than asserted in a document.

The two mechanisms cover the two obvious ways to fake a pass:

* **Delete the slow run** → its planned id now has no record → `OBS-MISSING-RUNS`
  blocks the pass, and the chain break is reported too.
* **Edit the slow run's number** → the record digest no longer matches its
  content → `LEDGER-INTEGRITY` blocks the pass.

## What this is and is not

This is **tamper evidence**, not tamper proofing. Someone who can rewrite the
whole file can recompute the whole chain. The value is that a *partial* edit —
which is what tidying an inconvenient result actually looks like — cannot pass
unnoticed, and that the plan/record mismatch is independent of the hash chain, so
both would have to be defeated together.

Publishing the head digest in the PR (and in the report's `ledger_digest`) is
what turns tamper evidence into something a reviewer can check against a later
copy.

## Verification

`tests/test_ledger.py` covers retention of failed and timed-out runs, deletion,
in-place edit, reordering, duplicate records, unplanned records, never-executed
planned runs, and the refusal to overwrite an existing plan.
`tests/test_evaluator.py::test_deleting_a_failed_run_cannot_manufacture_a_pass`
asserts that both keeping and deleting a failed run fail the sample, for
different recorded reasons.
