# Package A verification traceability

**Nothing in this table discharges a Must requirement clause.**

Appendix E.1 permits a coverage link to be discharged "only at or after the
covered requirement clause's release gate", and its own regression fixture states
that an AT-055/AT-056 CPU-feasibility pass still leaves the CR-025 integrated MVP
clause open. Package A has not run a learned model, has not run on a D-02-approved
host, and has produced no human quality evidence — so it has produced **no
witness** for any Must clause. What it has produced is *implementation evidence*:
the mechanisms those clauses will be verified against exist, are exercised, and
refuse to report a pass they have not earned.

Status values below:

* **implemented** — the mechanism exists and is exercised by a test;
* **partial** — some of the clause is implemented; the rest is named;
* **open** — not implemented in this package;
* **blocked** — cannot be implemented until an owner decision or a later package.

---

## §6.3 adapter lifecycle

| Operation | Implementation | Test | Status |
| --- | --- | --- | --- |
| `validate` | `core/validation.py`, `LocalExecutionService.validate` | `tests/test_validation.py` (19 tests) | implemented |
| `estimate` | `LocalExecutionService.estimate` → `ResourceEstimate` with all §6.3 fields, `is_measured=False` | `tests/test_contracts.py::test_estimates_and_observations_are_distinct_types` | implemented (heuristic basis, stated as such) |
| `submit` | `LocalExecutionService.submit` → immutable attempt id | `tests/test_execution_failures.py` | implemented |
| `status` | `LocalExecutionService.status` → `JobStatus` with state, progress, stage, diagnostics | `tests/test_execution_failures.py::test_only_one_render_runs_at_a_time` | implemented |
| `cancel` | `LocalExecutionService.cancel` → `CancelResult` reporting real granularity; the cancel predicate reaches **inside** managed pipe writes, native waits, anchor decode and output probing | `tests/test_execution_failures.py::test_cancellation_produces_a_cancelled_attempt_with_no_output`, plus 3 R4 tests (pipe write, supervised capture, cancelled encode publishes nothing) | implemented (DEC-0014 R4 second round) |
| Deadline expiry while probing is a **timeout**, not invalid output | `media/probe.py` raises `JobTimeoutError`; the file was never shown to be bad | `test_execution_failures.py::test_a_probe_deadline_is_classified_as_a_timeout_not_invalid_output` | implemented (DEC-0014 R4 second round) |
| Cleanup survivors are recorded, not discarded | `EncodeOutcome.survivors` → `AttemptRecord.cleanup_survivor_groups`; `ColdProcessEvidence.child_survivor_groups` | `test_execution_failures.py::test_teardown_reports_survivors_rather_than_assuming_success` | implemented (DEC-0014 R4 second round) |
| Effective controls (profile defaults + overrides) are validated before execution | `core/validation.py` resolves once and validates the resolved map; origin is re-attributed so an invalid **default** is not reported as a request control | `test_validation.py` (8 R5 cases) | implemented (DEC-0014 R5 second round) |
| `collect` | `LocalExecutionService.collect` → final immutable `AttemptRecord` | `tests/test_media_end_to_end.py` | implemented |
| `capabilities` | `FixtureAdapter.capabilities` → `Capabilities` | `tests/test_cli.py::test_capabilities_reports_the_non_qualifying_label` | implemented |

## §12.0 clauses

> **Formal qualification is gated shut in this build.**
> `bench/evaluate.py` carries `QUALIFICATION_IMPLEMENTATION_GAPS`, a
> non-overridable list of bindings a section 12.0 pass requires but which are
> not implemented: run evidence is not bound to the executed settings digest,
> profile revision and verified artifact digests; output manifests are not bound
> to the source anchor hashes actually executed; and quality/offline/device/
> workload evidence carries no references tying it to specific runs, outputs or
> environment. While that list is non-empty the evaluator returns
> `NOT_ELIGIBLE` for every input, whatever evidence is supplied. Removing
> entries is Package B/C work (DEC-0014).

| Clause | What exists | Test | Status |
| --- | --- | --- | --- |
| Core output: 640×360, 72 animation frames, 12 fps, 144 delivery frames at 24 fps, exactly 6 s | `contracts/media.py::P_L_FINAL_OUTPUT`, `media/cadence.py` | `test_cadence.py::test_core_output_is_exactly_six_seconds`; `test_media_end_to_end.py::test_the_fixture_renders_a_valid_six_second_640x360_clip` (decoded, not asserted from settings) | implemented |
| Separate source / synthesized / duplicated frame counts | `FrameAccounting` with enforced totals | `test_cadence.py::test_frame_accounting_separates_source_synthesized_and_duplicated` | implemented |
| First/last anchors at animation indices 0 and 71 | `AnchorSet.endpoints_match`, `VAL-ANCHOR-ENDPOINTS` | `test_validation.py::test_endpoints_must_sit_at_animation_index_0_and_71` | implemented |
| 2–4 approved anchors | `AnchorSet` min/max length, `VAL-PROFILE-ANCHOR-LIMIT` | `test_validation.py` (3 tests) | implemented |
| Warm boundary: submission → encoded file closed **and decodable** | `bench/runner.py` warm path; the boundary includes `validate_output` and `publish` | `test_benchmark_integration.py::test_warm_and_cold_runs_are_recorded_with_distinct_boundaries` | implemented |
| Process-cold boundary: timer starts before initialization | `bench/runner.py` launches a **fresh interpreter** inside the clock (`python -m animalite render --envelope`) and records `ColdProcessEvidence` with the child's own `(boot_id, pid, start_ticks)` instance marker | `test_benchmark_integration.py` (3 tests: timer placement under an injected delay, identical output warm vs cold, two distinct process instances) | implemented (DEC-0014 R3). Reconstructing the service in-process was **not** process-cold. **OS file cache is not cleared and the record says so** |
| Cold child executes the profile the parent resolved | `ExecutionEnvelope` carries the resolved profile and its digest; the child re-verifies it and resolves adapters only from its own allowlist; the parent re-checks the executed digest against the plan | `test_benchmark_integration.py::test_a_cold_run_executes_the_profile_the_parent_resolved`, `test_cli.py` (3 envelope tests) | implemented (DEC-0014 R3 second round) |
| A failing cold child keeps its attempt, category and diagnostics | the child's record is parsed before its exit status is judged; a record contradicting the process status is refused as a protocol error | `test_benchmark_integration.py` (4 tests: clean timeout, launcher exception, malformed output, contradictory success) | implemented (DEC-0014 R3/R4 second round) |
| One launch-to-completion deadline with bounded teardown; the plan continues after a supervisor failure | `COLD_TEARDOWN_GRACE_SECONDS`; `run_capture` supervises the whole group; `run()` contains per-run failures | `test_benchmark_integration.py::test_a_supervisor_timeout_is_recorded_and_the_next_run_still_executes` | implemented (DEC-0014 R3/R4 second round) |
| Preview: 3 s, 320×180, 12 animation fps | `PREVIEW_OUTPUT`, DEC-0005 | `test_media_end_to_end.py::test_the_preview_spec_renders_exactly_three_seconds_at_320x180` | implemented |
| Preview repetitions (36, three per clip) | DEC-0006; `ELIG-REPETITIONS` blocks a non-conforming plan | `test_evaluator.py` control case | implemented |
| Nearest-rank p95 `ceil(0.95 × n)`; n=36 → 35, n=12 → max | `bench/stats.py` | `test_stats.py` (18 tests) | implemented |
| Report n, all observations, median, p95, maximum | `DistributionSummary` | `test_benchmark_integration.py` | implemented |
| Failure handling: timeout / invalid output / missing observation fails the sample and stays in the ledger | `RunLedger` hash chain + declared plan; `OBS-FAILED-RUNS`, `OBS-MISSING-RUNS`, `LEDGER-INTEGRITY` | `test_ledger.py` (9 tests), `test_evaluator.py::test_deleting_a_failed_run_cannot_manufacture_a_pass` | implemented |
| Schedule integrity: the declared repetitions must match the actual per-clip schedule | `_check_plan_integrity`, `PLAN-SCHEDULE-MISMATCH`, `PLAN-ORDER-INVALID` | `test_evaluator.py::test_a_plan_whose_header_lies_about_repetitions_is_rejected` | implemented (was a false-pass hole; see DEC-0014 R1) |
| Record provenance: each record must be the planned run, from the evaluated plan/host/profile, non-exploratory | `_check_record_identity`, `REC-*` findings | `test_evaluator.py::test_records_from_another_profile_or_host_cannot_stand_in` | implemented (DEC-0014 R1) |
| Input identity: dataset and profile **content digests**, plus target revision and host **id**, must match the frozen plan. Host and target are bound by identifier/revision, **not** by a digest of their contents: a host whose hardware changed under a stable `host_id` would still match | `ELIG-DATASET-DIGEST`, `ELIG-PROFILE-DIGEST`, `ELIG-TARGET-REVISION`, `ELIG-HOST-IDENTITY` | `test_evaluator.py` (2 tests) | partial (DEC-0014 R1); content binding for host/target is not implemented |
| Sustained workload is an outcome, not a duration | `_check_continuous_workload`: thermal status, latency/memory breach, group memory scope and limit, swap reliance | `test_evaluator.py` (3 tests) | implemented (DEC-0014 R2) |
| Licence admission (C-04, CR-024) | `ELIG-LICENCE-NOT-CLEARED`, `ELIG-LICENCE-MISSING` | `test_evaluator.py` | implemented (DEC-0014 R2) |
| No passing score from successful runs only | evaluator blocks on any failure or missing run | `test_evaluator.py` | implemented |
| Sample composition 4/4/4, ≥2 two-anchor clips, locked | `ELIG-DATASET-*` findings | `test_evaluator.py` (3 tests) | implemented (**the sample itself is not frozen**) |
| Batch size one, fixed randomized order with recorded seed | `build_plan`, `ELIG-BATCH-SIZE`; one render at a time enforced by the service | `test_execution_failures.py::test_only_one_render_runs_at_a_time` | implemented |
| Quality: 12 clips, two reviewers, ≥8/10, no zero, no severity 2/3 | `QualityReview` + `QUAL-*` findings | `test_evaluator.py` (4 tests) | mechanism implemented; **no review has been performed** |
| Peak application-group memory ≤ 4 GiB, method disclosed | `MemorySampler`, `MemoryObservation`, `OBS-MEMORY-*` | `test_evaluator.py` (2), `test_media_end_to_end.py` | mechanism implemented; DEC-0009 records the scope limits |
| Continuous 20-minute workload with thermal/power observations | `ContinuousWorkloadRecord`, `OBS-CONTINUOUS-WORKLOAD` | `test_evaluator.py::test_a_missing_continuous_workload_blocks_the_pass` | contract only — **not executed** |
| Fresh-input packs ≤ 5 min active / ≤ 30 s preprocessing | `FreshInputPackRecord`, `AT056-*` | `test_evaluator.py` (2) | contract only — **not executed** |
| Four unsupported cases rejected before synthesis | `UnsupportedCaseRecord`, `AT056-UNSUPPORTED-CASES` | `test_evaluator.py` | contract only — **not executed** |
| Offline rerun and runtime/device trace | `EvidenceBundle` statuses, `AT056-OFFLINE`, `AT055-DEVICE-TRACE` | `test_evaluator.py` | contract only — **not executed** |
| 720p extension (Should) | — | — | open |
| Real-time factor ≤ 10 at p95 | derivable from p95 and output duration but not computed | — | open |

## Requirement-level position

| ID | Package A contribution | Discharged? |
| --- | --- | --- |
| SM-19 | none — no measured pass exists | **No.** Blocked on D-02 host approval, a learned adapter and quality review. |
| CR-004 | Cadence locked in `CadencePolicy`; duplication is the only implemented conversion; interpolated uplift is rejected with `VAL-CADENCE-UNSUPPORTED` | No — D-09 still governs the policy |
| CR-006 | `ResourceEstimate` is device-class agnostic; accelerator fields optional | Implementation evidence only |
| CR-010 | Pinned settings + `EnvironmentRecord` (commit, dirty flag, tool identities, lock digest, CPU/SIMD flags, thread env) | Partial — cross-host pixel-equivalence comparison not implemented |
| CR-025 | none — this is the gate Package A exists to prepare for | **No** |
| MR-010 | Validation runs before any encode; rejections are recorded as failed attempts | Implementation evidence only |
| MR-013 | Thread budget, memory method, storage and stage timings recorded per attempt | Partial — setup/attempt/cost fields await real profiles |
| MR-015 | No network client exists in the package; `DeviceEvidence.network_calls_observed_status` is `pending`, not asserted | **No** — honest `pending`, not a claim |
| MR-016 | `EngineProfile` declares class, tiers, required assets and CPU-only guarantee | Implementation evidence only |
| MR-018 | **Structurally cannot be satisfied here.** Three independent mechanisms prevent a false claim (DEC-0008) | **No** |
| NFR-002 | Failed attempts retain diagnostics; retry creates a new linked attempt | Implementation evidence only |
| NFR-003 | Anchors, outputs, settings and the ledger are all content-hashed | Implementation evidence only |
| NFR-013 | Structured JSONL logs per attempt with stage, duration, failure category | Implementation evidence only |
| NFR-015 | Output-affecting settings serialized and hashed via `settings_digest()` | Implementation evidence only |
| NFR-019 | Duplication-only conversion; pinned scaler; no silent resampling | Implementation evidence only |
| NFR-028 | Timing boundaries, frame counts, memory method and evidence statuses are all recorded and reported | Implementation evidence only |
| C-05 | Approved inputs are never written; published output is never overwritten; retry never mutates the parent | `test_execution_failures.py` (3 tests) |

## AT-055 / AT-056

**Both are NOT RUN and cannot be run from this repository.** Prerequisites:

| Prerequisite | State |
| --- | --- |
| A learned CPU temporal adapter with participating learned synthesis | Not implemented (Package B) |
| Verified upstream code + weight licences for that adapter | Not started (LIC-05) |
| D-02-approved P-L host with recorded SKU, power and thermal policy | Not approved |
| D-02-signed §12.0 targets | Not signed — targets remain proposed |
| Frozen 12-clip sample with locked hashes, indices and rights records | Not frozen (LIC-07) |
| Two named quality reviewers | Not assigned |
| Four fresh input packs; four unsupported cases; offline rerun; device trace | Not produced |

Every one of these is checked by `bench/evaluate.py`, and each missing item
produces a specific blocking finding. Running the harness today against the
fixtures yields `verdict: not_eligible` with 19 blocking findings — see
`docs/verified-commands.md`.

## Phase gate position

| Gate | State |
| --- | --- |
| Phase 0 exit (D-01, D-02) | **Open.** No agent action can close it. |
| Phase 1 CPU feasibility gate (AT-055 + AT-056 on the pinned P-L host) | **Open.** |
| Phase 1 early gate, Phase 1 exit, Phase 2 exit | **Open.** |

No phase gate has passed, and no evidence in this repository should be read as
passing one.
