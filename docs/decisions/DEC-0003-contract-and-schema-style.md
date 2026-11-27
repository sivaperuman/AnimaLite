# DEC-0003 — Contract and schema style

* **Status:** Accepted
* **Deciding role:** implementation
* **Affects:** requirements §10, §11 API rules, handoff v0.2 rule 2

## Decision

1. **Every contract is closed.** `Contract` sets `extra="forbid"` and
   `frozen=True`. An unknown field is a validation error, not a dropped value.
2. **Documents are versioned.** Anything written to disk on its own extends
   `Document` and carries `schema_version` (currently
   `animalite.contracts/v1`).
3. **Digests are canonical.** `canonical_json()` produces sorted-key, compact,
   UTF-8, NaN-rejecting bytes; `content_digest()` hashes that. Output-affecting
   settings are hashed through `RenderRequest.settings_digest()`, which
   deliberately excludes `request_id`, `label`, `timeout_seconds` and
   `parent_attempt_id` — those change bookkeeping, not pixels.
4. **Absent is not zero.** `EvidenceStatus` distinguishes `measured` from
   `unavailable` / `pending` / `not_applicable`, and `MemoryObservation` refuses
   to carry a value unless the status is `measured` — and refuses a `measured`
   status with no value.
5. **Estimates and observations are different types.** `ResourceEstimate` carries
   `kind="estimate"`, `is_measured=False` and a `basis` string saying how it was
   derived. Nothing merges an estimate into a measured record.
6. **Invariants live in the type.** A `FrameAccounting` whose parts do not sum
   correctly cannot be constructed; nor can a succeeded attempt without an output
   manifest, a failed attempt that publishes one, an over-allocated
   `ThreadBudget`, or a benchmark report that claims a pass while carrying
   blocking findings.

## Why

The handoff asks for behaviour to be explicit and for unknown critical fields not
to be silently ignored. Putting these rules in the type system rather than in
review checklists means a later change cannot quietly violate them: the tests
that assert them are asserting behaviour the constructor enforces, not comments.

Rule 6 in particular is what makes "no false pass" structural. The most valuable
single line in the contracts is arguably the `EngineProfile` validator that
refuses `qualification_eligible=True` when `learned_temporal_participation` is
`False` — a mislabelled profile is rejected at construction, before any harness
logic runs.

## Scope note

`ShotIntent` models only the identity, timing, format, creative, keyframe and
routing groups of the §10.2 shot manifest. The layers, controls, audio,
`rights_inputs`, `rights` and review groups are **absent rather than stubbed**,
because a placeholder rights field would look like a rights record. They arrive
with the work packages that implement them.

## Reversal

Adding a field is routine. Removing one, renaming an enum value, or relaxing
`extra="forbid"` is a schema change: bump `SCHEMA_VERSION` and state the
migration.
