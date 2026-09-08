# Verified commands and observed output

Every command below was **executed** on the platform recorded here, from a clean
virtual environment created for this record. This file is evidence, not
instructions written from memory: where a command's output is quoted, that is
what it printed.

## Development platform

| Item | Value |
| --- | --- |
| OS | Ubuntu 24.04.4 LTS |
| Kernel | 6.18.44-fc-v24 |
| CPU | Intel(R) Xeon(R) Processor @ 2.80GHz (4 physical / 4 logical cores; avx2, avx512f, fma, sse4_2 recorded) |
| RAM | 16 856 092 672 bytes |
| Python | Python 3.11.15 |
| FFmpeg | `ffmpeg version 6.1.1-3ubuntu5 Copyright (c) 2000-2023 the FFmpeg developers` |
| Dependency lock | `constraints/dev-linux-cpython311.txt` |

> **This is a hosted development container, not a P-L host.** It has no D-02
> approval, its CPU is virtualized, and its cgroup peak counter covers processes
> outside the render. Every timing below is **exploratory** and is not a section
> 12.0 result. Handoff §8: "Do not call a hosted runner's timing a P-L result."

## 1. Clean install

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]" -c constraints/dev-linux-cpython311.txt
```

Resolved exactly the pinned set: `animalite 0.1.0`, `pydantic 2.13.5`,
`pydantic-core 2.46.5`, `numpy 2.4.6`, `annotated-types 0.8.0`,
`typing_extensions 4.16.0`, `typing-inspection 0.4.4`, plus the dev tools
`pytest 8.4.2`, `ruff 0.16.6`, `mypy 1.20.2` and their transitives. Exit 0.

## 2. Quick checks

| Command | Result |
| --- | --- |
| `ruff check --no-cache .` | `All checks passed!` — exit 0 |
| `ruff format --no-cache --check .` | `85 files already formatted` — exit 0 |
| `mypy` (with `.mypy_cache` removed) | `Success: no issues found in 57 source files` — exit 0 (strict mode for `src/`) |
| `python -m pytest -m "not slow" -q -p no:cacheprovider` | `185 passed, 41 deselected in 60.85s` — exit 0 |
| `python -m pytest -q -p no:cacheprovider` | `226 passed in 148.51s` — exit 0 |

> **Why the caches are disabled here.** The first CI run failed on `ruff check`
> with four `I001` import-order findings that a local `ruff check .` had just
> reported clean. Cause: adding `tests/__init__.py` (needed for mypy's module
> mapping) reclassified `tests` from third-party to first-party for isort, but a
> stale `.ruff_cache` reused the earlier verdict for those four files. Fixed by
> declaring `known-first-party = ["animalite", "tests"]` explicitly in
> `pyproject.toml` so the classification no longer depends on inference or cache
> state, and by re-running every check with its cache disabled — which is what
> this table now records. CI checks out fresh, so it never saw a stale cache;
> the local run did.

## 3. Entry points

```
$ animalite --version
animalite 0.1.0

$ python -m animalite --version
animalite 0.1.0
```

Both entry points work; `python -m animalite` is the documented fallback.

## 4. Host inventory

```bash
animalite doctor
animalite doctor --json
```

Recorded the CPU model, 4 physical / 4 logical cores, the SIMD flags, RAM,
Python identity, both FFmpeg tools with their versions and full build
configuration, and the available memory-measurement method
(`cgroup_v2_memory_peak`). It reported:

```
host approval: NOT APPROVED - inventory only, never a D-02 decision
warning      : ffmpeg is a GPL-configured build; its terms flow from the enabled
               components. See THIRD_PARTY_NOTICES.md and docs/licensing.md.
```

With FFmpeg made unavailable, `animalite doctor --json` exits **3** and reports
both tools as unavailable with the reason. It never fabricates a value.

## 5. Reproducible fixture generation

```bash
animalite fixtures generate --out-dir work/fixture
```

Generated four development clips with stable anchor hashes, e.g.
`fixture-two-anchor` at animation indices `[0, 71]`:

```
sha256:c046d79e8fcaa0eec374b9aa1270425c1de176688621e9e044ad6680b9322194
sha256:ded761ed20ef8943d3cf73aa9d55b224726584841fcf8af0fb6ba7053a649973
```

and a `dataset.json` with `purpose: development`. It printed
`fixture artwork is test material, not benchmark evidence` on stderr.
Reproducibility is asserted by
`tests/test_media_end_to_end.py::test_the_fixture_generator_is_reproducible`,
which generates the same clip twice into different directories and compares
hashes.

## 6. One small local example — the end-to-end fixture encode

```bash
animalite render --profile fixture-synthetic \
  --anchors work/fixture/fixture-two-anchor/anchors.json \
  --workspace work/ws --shot-code FIXTURE-2A
```

```
state     : succeeded
profile   : fixture-synthetic
wall (s)  : 0.696082
output    : work/ws/attempts/att-.../output/output.mp4
hash      : sha256:65057667350528a6273b393406d7c195515991b05c2e6aebc678c954ae8f007d
decoded   : 640x360 h264/High yuv420p 144 frames @ 24/1 = 6.0s
frames    : source=2 synthesized=70 duplicated=72 (animation=72, delivery=144)
qualifying: False
            fixture adapter: deterministic eased cross-dissolve between approved
            anchors, with no learned component. MR-018 excludes cross-fades and
            repeated source frames from learned temporal capability, so no output
            from this adapter is evidence for AT-055/AT-056.
memory    : measured 1373028352 bytes via cgroup_v2_memory_peak
```

The `decoded:` line is what **ffprobe reported after decoding the published
file**, not a restatement of the requested settings: 144 delivery frames counted
by `-count_frames`, 24/1 average frame rate, 6.0 s duration. The 0.696 s wall
time is the deterministic fixture blend, not a model, on an unapproved host.

## 7. Validation

```bash
# valid request
animalite validate --profile fixture-synthetic --anchors .../anchors.json
# -> valid (1 non-blocking issue(s)); exit 0
#    [warning] VAL-NON-QUALIFYING-PROFILE ... its output is not qualification evidence

# unsupported control
animalite validate ... --control optical_flow_strength=0.8
# -> invalid: [VAL-CONTROL-UNSUPPORTED] the fixture adapter does not implement
#    control 'optical_flow_strength'
#    -> Remove the control or choose a profile whose capabilities() lists it.
#       Supported: ease, drift_pixels.
# exit 2
```

Even a *valid* fixture request carries the non-qualifying warning.

## 8. Failure path — deadline, cleanup and retained diagnostics

```bash
animalite render --profile fixture-synthetic \
  --anchors work/fixture/fixture-four-anchor/anchors.json \
  --workspace work/ws-timeout --timeout 0.35
```

```
state     : failed
failure   : [timeout] job deadline of 0.132s elapsed after 38 of 144 delivery
            frames; the encoder process group was torn down and no output was
            published
diagnostics: work/ws-timeout/attempts/att-.../diagnostics
```

Exit **1**. Verified afterwards:

| Check | Result |
| --- | --- |
| `output/` contents | 0 files — nothing was published |
| `diagnostics/` contents | `encoder.stderr.log`, `output.mp4.partial` — retained, named so it cannot be mistaken for output |
| `state` in `attempt.json` | `failed` |
| `failure.category` | `timeout` |
| `output` in `attempt.json` | `None` |
| orphan `ffmpeg` children | 0 |

("0.132s" is the deadline *remaining* when the encode stage began; validation and
anchor decode consumed the rest of the 0.35 s budget. The deadline is enforced
once per delivery frame — see the note on granularity in `RenderRequest`.)

Automated coverage of the same behaviour, including adapter crashes,
short/oversized adapter streams, wrong frame geometry, cancellation, retry
linkage and attempt immutability, is in `tests/test_execution_failures.py`.

## 8b. Second-round repairs (R3, R4, R5) — before and after

Each defect was reproduced on `8ba39f5` before it was fixed, then re-measured on
the same machine. The reproduction scripts drive the public API only.

| Behaviour | Before | After |
| --- | --- | --- |
| Cold run of a plan whose parent registered an **overridden** `fixture-synthetic` (`ease=linear, drift_pixels=12`) | warm `sha256:5fb314b0…`, cold `sha256:65057667…` — the *default* profile's output, both recorded `succeeded` | warm and cold both `sha256:5fb314b0…` |
| `ColdProcessEvidence.child_pid` | `None` on every run (`subprocess.CompletedProcess` has no `pid`; the `hasattr` fallback masked it) | real pids, e.g. `21591`, `22612`, `22720`, `22899`, each with a distinct `(boot_id, pid, start_ticks)` marker and `survivors=[]` |
| Cold child that hits its job deadline (exit 1 with a valid failed record on stdout) | `outcome=failed`, `attempt_id=None`, `category=internal_error`, no diagnostics link | `outcome=timeout`, real `attempt_id`, `category=timeout`, diagnostics path present, `failure_elapsed_seconds` recorded separately from `wall_seconds` |
| `subprocess.TimeoutExpired` injected at the cold launch, 2 planned runs | escaped `run()`; **0 of 2** ledger rows | contained per run; **2 of 2** ledger rows, plan continues |
| `cancel()` at 0.30 s against a child that ignores stdin for 3 s, 600 s job deadline | returned at **3.010 s**, as `BrokenPipeError` when the child exited on its own | returned at **0.324 s**, as `ProcessCancelled`, group torn down |
| `validate` with `controls={"drift_pixels": "not-a-number"}` | `valid=True`, **zero errors**; later raised inside synthesis | `valid=False`, `VAL-CONTROL-VALUE-INVALID` at `controls.drift_pixels` |
| Same, but the bad value is a *profile default* with no override | not checked at all | `valid=False`, attributed to `engine_profile.parameters.drift_pixels` |
| Same bad default **with** a valid override | not checked at all | `valid=True` — synthesis would never have read that default |

The replaced timing test is worth naming: `min(cold) > min(warm)` was asserted as
a correctness invariant. It is not one on a shared runner, and it can fail from
noise alone. Timer placement is now proved by injecting a known delay at the
launch boundary and requiring the recorded cold wall time to have absorbed it.

## 8c. Third-round repairs (R3, R4, R5) — before and after

Reproduced on `94cfc5a` before fixing, then re-measured. **Two of these were
regressions introduced by the second round's own fixes**, and are marked as such.

| Behaviour | Before | After |
| --- | --- | --- |
| Cold run with the parent holding injected tool identities | warm recorded `parent-only-ffmpeg / PARENT-INJECTED`; cold silently ran host-discovered `ffmpeg 6.1.1-3ubuntu5`; **both `succeeded`** under one plan | cold is `failed`: *"the media tools resolved here are not the ones this job was built for"* |
| Cold run on incomplete process evidence | accepted as `succeeded` | rejected: missing/unidentified marker, pid disagreement, non-distinct instance, or any survivor group |
| **Regression from round 2** — `timeout=0.15`, child closes fd 1/2 then sleeps 0.20 s | **SUCCESS after 0.225 s** — the 250 ms reap floor made the deadline non-authoritative | `ProcessTimeout` after **0.171 s** |
| Same child sleeping 0.60 s | `TimeoutError` after 0.280 s | `ProcessTimeout` after **0.171 s** |
| **Regression from round 2** — teardown forced through every phase, budget 0.5 s | ~1.0 s+: TERM wait, KILL wait and group sweep each started a fresh window | **0.500 s** total, survivors reported |
| An expired job deadline | `max(0.1, …)` renewed a 100 ms allowance, so the next decode/encode/probe still launched | raises before another native child is started |
| A leaked encoder group | noted, then the run went on to probe and **publish** | `CleanupFailed`, nothing published, groups recorded on the attempt and in the ledger |
| `drift_pixels = 10**1000` (contract-valid) | `OverflowError: int too large to convert to float` escaped `validate_request` | `VAL-CONTROL-VALUE-INVALID` |

The two regressions share a shape worth naming: each was an *allowance* added to
make a fix comfortable — a reap floor so a just-finished child would not be
called a timeout, a teardown grace so cleanup had room — and each quietly
re-opened the guarantee it sat beside.

## 8d. Fourth-round repairs (R3, R4) — before and after

Reproduced on `2917cbe` before fixing. The reviewer's measured figures
reproduced to the digit (`0.200` / `0.401`, and the accepted `succeeded` run
under `/usr/bin/ffmpeg`).

| Behaviour | Before | After |
| --- | --- | --- |
| Unavailable tool pair in the parent, host FFmpeg still on `PATH` | cold run **`succeeded`**, having executed `/usr/bin/ffmpeg` — the contract switched itself off | `failed`, `category=tool_unavailable`, **no child launched** |
| Two **absent** content hashes compared | `mismatches() == []`, i.e. treated as equal | 2 problems, both "the executable identity is unverified and cannot be accepted" |
| Warm-run tool identity | recorded with **no content hash** | hashed, identical to the cold identity |
| `terminate_tree()` then `close()`, budget 0.2 s | **0.200 s**, then **0.401 s** — the budget restarted per call | 0.201 s, then **0.202 s** |
| Encoder that consumed every frame then hung | the final wait renewed 100 ms via `max(0.1, …)` | times out, tears down, publishes nothing |
| Injected `ProcessTimeout(pid=424242, survivors=(777,))` at the cold boundary | `cold_process_evidence=None`, `cleanup_survivor_groups=[]` | `child_pid=424242`, `child_survivor_groups=[777]`, `cleanup_survivor_groups=[777]` |

### A correction our own tests caught

Making the teardown budget lifecycle-scoped first left a **zombie child**: with
the budget spent, the post-`SIGKILL` `wait()` got zero seconds, so the process
was killed but never reaped and still showed under `pgrep -P`.
`test_a_job_timeout_kills_the_encoder_and_leaves_no_orphan` failed and named it.

Reaping after `SIGKILL` now has its own small bounded allowance. That is **not**
the reap floor R4.1 removed: that floor let a *still-running* process be reported
as a success, whereas `SIGKILL` cannot be caught — the process is already dead
and `waitpid` is collecting a corpse. Skipping it buys nothing and leaves a
zombie.

## 9. Benchmark harness against the fixtures

```bash
animalite benchmark run \
  --dataset work/fixture/dataset.json \
  --host benchmarks/hosts/development-unapproved.json \
  --targets benchmarks/targets/section-12-0-proposed.json \
  --profile fixture-synthetic \
  --ledger work/bench/ledger --workspace work/bench/ws \
  --warm-repetitions 1 --cold-repetitions 1 --preview-repetitions 1
```

```
verdict : not_eligible
label   : EXPLORATORY -- NOT QUALIFICATION EVIDENCE. This report does not
          establish any section 12.0 result and does not discharge AT-055 or AT-056.
host    : development-unapproved (approved=False)
profile : fixture-synthetic (qualification_eligible=False)
ledger  : sha256:2f27ab200f19146e7fd8d72b032c798a629db0cb53c152c2c90d3efe22392fc2 verified=True
  warm_final    planned=4 succeeded=4 failed=0 missing=0 median=0.7252415 p95=0.847076 (index 4) max=0.847076
  cold_final    planned=4 succeeded=4 failed=0 missing=0 median=0.8318435 p95=0.915124 (index 4) max=0.915124
  warm_preview  planned=4 succeeded=4 failed=0 missing=0 median=0.3891695 p95=0.448683 (index 4) max=0.448683
blocking findings: 19
```

**All 12 runs succeeded and the verdict is still `not_eligible`** — which is the
point. The 19 blocking findings were:

`ELIG-PROFILE-NOT-LEARNED`, `ELIG-NO-LEARNED-TEMPORAL`, `ELIG-HOST-UNAPPROVED`,
`ELIG-HOST-NO-INVENTORY`, `ELIG-HOST-NO-POWER-POLICY`, `ELIG-TARGETS-UNAPPROVED`,
`ELIG-DATASET-NOT-LOCKED`, `ELIG-DATASET-COMPOSITION`, `ELIG-REPETITIONS` (×2),
`QUAL-REVIEWERS-MISSING` (×4), `AT056-FRESH-PACKS`, `AT056-UNSUPPORTED-CASES`,
`OBS-CONTINUOUS-WORKLOAD`, `AT056-OFFLINE`, `AT055-DEVICE-TRACE`.

Each names the requirement it comes from. The three latency numbers above are
exploratory fixture timings on an unapproved host; they are **not** evidence
against the §12.0 warm/cold/preview targets, and nothing in the report presents
them as such.

## 10. A deleted run cannot produce a pass

```bash
cp -r work/bench/ledger work/bench/ledger-tampered
head -11 work/bench/ledger/runs.jsonl > work/bench/ledger-tampered/runs.jsonl   # drop one run
animalite benchmark report --ledger work/bench/ledger-tampered \
  --dataset work/fixture/dataset.json \
  --host benchmarks/hosts/development-unapproved.json \
  --targets benchmarks/targets/section-12-0-proposed.json
```

```
ledger  : sha256:600ab265... verified=False
blocking findings: 21          (up from 19)
  - [OBS-MISSING-RUNS] 1 of 4 warm_preview runs have no record; a missing
    required observation fails the sample
  - [LEDGER-INTEGRITY] run ledger integrity problem: 1 planned run(s) have no
    record: ['fixture-four-anchor:warm_preview:1']
```

Both the declared-plan check and the hash chain caught it, independently.
`tests/test_ledger.py` covers deletion, in-place edit, reordering, duplicates
and unplanned records.

## 11. Pending behaviour when FFmpeg is absent

```bash
ANIMALITE_FFMPEG=/nonexistent ANIMALITE_FFPROBE=/nonexistent \
  PATH=/usr/bin:/bin python -m pytest -q -m media
```

`3 passed, 29 skipped`, each skip reading:

```
PENDING (not run): FFmpeg tooling unavailable: ffmpeg not found on PATH and
ANIMALITE_FFMPEG is unset or points at a missing file; ...
```

A media-dependent test reports *pending*; it never passes vacuously.

## Exit codes

| Code | Meaning | Observed for |
| --- | --- | --- |
| 0 | success | `doctor` (tools present), `validate` (valid), `render` (succeeded), `benchmark run` (report generated) |
| 1 | operation failed | `render` with a deadline shorter than the render; `render` with an unknown profile |
| 2 | request is invalid | `validate` with an unsupported control |
| 3 | required tooling unavailable | `doctor` with FFmpeg missing |

## Commands that do **not** exist

No command in this repository downloads model weights, executes a learned model,
runs the §12.0 qualification matrix, or produces qualification evidence. Their
prerequisites are listed in `docs/verification/package-a-traceability.md`.
