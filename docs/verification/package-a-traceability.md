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
| `cancel` | `LocalExecutionService.cancel` → `CancelResult` reporting real granularity | `tests/test_execution_failures.py::test_cancellation_produces_a_cancelled_attempt_with_no_output` | implemented |
| `collect` | `LocalExecutionService.collect` → final immutable `AttemptRecord` | `tests/test_media_end_to_end.py` | implemented |
| `capabilities` | `FixtureAdapter.capabilities` → `Capabilities` | `tests/test_cli.py::test_capabilities_reports_the_non_qualifying_label` | implemented |

## §12.0 clauses

| Clause | What exists | Test | Status |
| --- | --- | --- | --- |
| Core output: 640×360, 72 animation frames, 12 fps, 144 delivery frames at 24 fps, exactly 6 s | `contracts/media.py::P_L_FINAL_OUTPUT`, `media/cadence.py` | `test_cadence.py::test_core_output_is_exactly_six_seconds`; `test_media_end_to_end.py::test_the_fixture_renders_a_valid_six_second_640x360_clip` (decoded, not asserted from settings) | implemented |
| Separate source / synthesized / duplicated frame counts | `FrameAccounting` with enforced totals | `test_cadence.py::test_frame_accounting_separates_source_synthesized_and_duplicated` | implemented |
| First/last anchors at animation indices 0 and 71 | `AnchorSet.endpoints_match`, `VAL-ANCHOR-ENDPOINTS` | `test_validation.py::test_endpoints_must_sit_at_animation_index_0_and_71` | implemented |
| 2–4 approved anchors | `AnchorSet` min/max length, `VAL-PROFILE-ANCHOR-LIMIT` | `test_validation.py` (3 tests) | implemented |
| Warm boundary: submission → encoded file closed **and decodable** | `bench/runner.py` warm path; the boundary includes `validate_output` and `publish` | `test_benchmark_integration.py::test_warm_and_cold_runs_are_recorded_with_distinct_boundaries` | implemented |
| Process-cold boundary: timer starts before initialization | `bench/runner.py` constructs a fresh service inside the clock | same | implemented; **OS file-cache state is not cleared and the plan notes say so** |
| Preview: 3 s, 320×180, 12 animation fps | `PREVIEW_OUTPUT`, DEC-0005 | `test_media_end_to_end.py::test_the_preview_spec_renders_exactly_three_seconds_at_320x180` | implemented |
| Preview repetitions (36, three per clip) | DEC-0006; `ELIG-REPETITIONS` blocks a non-conforming plan | `test_evaluator.py` control case | implemented |
| Nearest-rank p95 `ceil(0.95 × n)`; n=36 → 35, n=12 → max | `bench/stats.py` | `test_stats.py` (18 tests) | implemented |
| Report n, all observations, median, p95, maximum | `DistributionSummary` | `test_benchmark_integration.py` | implemented |
| Failure handling: timeout / invalid output / missing observation fails the sample and stays in the ledger | `RunLedger` hash chain + declared plan; `OBS-FAILED-RUNS`, `OBS-MISSING-RUNS`, `LEDGER-INTEGRITY` | `test_ledger.py` (9 tests), `test_evaluator.py::test_deleting_a_failed_run_cannot_manufacture_a_pass` | implemented |
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
