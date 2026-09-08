# DEC-0008 — The fixture adapter boundary

* **Status:** Accepted
* **Deciding role:** implementation
* **Affects:** MR-018, MR-016, AT-055, AT-056, handoff v0.2 §13 item 4

## Decision

Package A ships exactly one adapter, `fixture-synthetic`. It:

* produces intermediate frames by **deterministic eased cross-dissolve** between
  the two bracketing approved anchors, plus a deterministic sub-pixel drift;
* reproduces each approved anchor exactly at its own animation index;
* declares `engine_class=deterministic`,
  `learned_temporal_participation=False`, `qualification_eligible=False` and a
  `non_qualifying_reason` that cites MR-018 by name;
* passes its frames through the **real** CPU media path — same cadence
  expansion, same streaming encoder, same decode validation, same publish rules
  as any future learned adapter.

`animalite render` requires an explicit `--profile`. There is no default engine.

## Why it can never qualify — and why that is enforced, not documented

MR-018 states that "camera transforms, cross-fades, repeated source frames, stock
loops and pre-authored dense animation alone cannot satisfy this requirement". A
cross-dissolve is squarely in that list. So the honest position is not "this
adapter has not been qualified yet" but "this adapter is categorically incapable
of qualifying".

Three independent mechanisms enforce it, so no single edit can produce a false
claim:

1. **The profile contract** refuses to construct an `EngineProfile` with
   `qualification_eligible=True` and `learned_temporal_participation=False`, and
   refuses eligibility for any `engine_class=deterministic` profile.
2. **The output manifest** of every render carries
   `is_qualifying_evidence=False` plus the reason, and the manifest contract
   refuses a non-qualifying label with no reason.
3. **The evaluator** emits blocking `ELIG-PROFILE-NOT-LEARNED` and
   `ELIG-NO-LEARNED-TEMPORAL` findings, which force `not_eligible` regardless of
   how good the timings are.

Validation additionally attaches a non-blocking `VAL-NON-QUALIFYING-PROFILE`
warning to every fixture request, so even a successful validation says so.

## Why a fixture adapter at all

Handoff §13 item 4 asks for one: "A small, clearly named fixture adapter that
produces actual intermediate frames and passes them through the real CPU
media/encode path... Include a reproducible fixture generator so no private
artwork, large download or model weight is needed."

Without it, the media pipeline, attempt lifecycle, failure paths and benchmark
harness could only be tested against mocks — and handoff rule 3 requires the CLI
and benchmark to exercise one real execution path. The fixture adapter is what
makes the rest of Package A verifiable today.

## Reproducible fixture artwork

`animalite fixtures generate` renders flat-shaded synthetic anchors from a seed
using closed-form arithmetic per (clip, index) — no RNG state carried between
frames — so any single anchor regenerates bit-for-bit. A test asserts hash
equality across two independent generations. This artwork is test material; it is
explicitly *not* the §12.0 locked 12-clip sample, and the generated dataset
manifest says so in its notes and carries `purpose: development`.
