# AnimaLite engineering instructions

## Objective and authority
- Project: AnimaLite; Python package and CLI: `animalite`.
- Prove useful short video from 2–4 approved frames on CPU/low-spec hardware.
- Requirements v0.12 and approved amendments define acceptance. The source
  document is `docs/requirements/Frame_Conditioned_2D_Video_System_Requirements_v0.12.docx`;
  `docs/requirements/cpu-stage-extract.md` is a labelled CPU-stage extract, not a
  replacement for it.
- Read CPU §§6.0, 6.3, 12.0, AT-055/056 and Appendix E before related work.
- Keep proposed thresholds and unmeasured performance labelled as such.
- Preserve owner authority for scope, hardware, budget, rights and go/no-go.
- Use the recommended PolyForm Noncommercial license for original project software;
  preserve third-party terms and describe the project as source-available.

## Current implementation scope
- Package A (this repository's current state): contracts, CLI, local execution
  service, CPU media pipeline, host inventory, benchmark harness and one
  deterministic fixture adapter.
- Build the CLI, common contracts and benchmark first, then one learned CPU adapter.
- Use one classical comparator; it cannot itself satisfy learned temporal
  capability. Implemented as `classical-warp-baseline` (DEC-0015): block matching
  in NumPy, structurally barred from qualifying. When it passes the same example
  the learned candidate passes, that does not negate learned participation — it
  means that example cannot identify the mechanism or show a learned advantage.
  Keep the comparator credible and compare on the same inputs and envelope;
  never weaken it to manufacture a win.
- Keep UI, episode services, cloud/GPU branches and training outside the first proof.
- Missing hardware evidence leaves qualification pending; continue useful coding.

## Coding
- Keep domain contracts independent of native model libraries. `animalite.core`
  and `animalite.contracts` must not import a model runtime; adapters are reached
  only through `animalite.adapters.registry.Registry`.
- Respect the layer direction: `contracts` and the leaf modules (`errors`, `proc`,
  `resources`, `admission`) sit below `media`, which sits below `adapters`, which
  sits below `core`. A lower layer never imports a higher one, and `tests/test_import_layering.py`
  enforces this by importing each subpackage first in a fresh interpreter.
- Use typed, versioned schemas; make units, frame indexing and device policy explicit.
  Every contract sets `extra="forbid"`: an unknown field is an error, not a
  dropped value.
- Stream frames with bounded memory; pin total threads and batch size.
- Retain immutable attempts, failure diagnostics and safe process cleanup. A
  retry creates a new attempt linked to its parent; it never rewrites one.
- Use explicit CPU runtime/encoder selection; never silently fall back remotely.
- Invoke native tools with argument arrays, never a shell string.
- Bound every native call by what is left of the *job* deadline and the job's
  cancel predicate, through `animalite.proc.run_capture`. A private per-call
  timeout is not a bound: the adapter generator is pulled synchronously by the
  encoder, so nothing else can enforce anything while one call is stalled.
- Executing third-party model artifacts needs a recorded admission decision
  covering those exact digests and the run's purpose (`animalite.admission`,
  DEC-0016). Verifying a digest answers a different question. Missing, pending
  and rejected all block execution, and there is no development bypass.
- Never execute bytes that have not verified against their pinned digest — not
  to print a version banner, not to probe compatibility. Read the file instead.
- Distinguish an absent observation from a measured zero. `EvidenceStatus` and the
  `MemoryObservation` validator exist for exactly this.
- Keep model weights, secrets, caches and large evidence out of source commits.

## Verification
- CLI and benchmark must call the same real execution path
  (`animalite.core.service.LocalExecutionService`).
- Test observable contract/failure risks with tiny fixtures in default CI.
- Keep failed/timed-out/missing benchmark runs; never turn missing data into a pass.
- Report full timing boundaries, output counts, memory and actual runtime identity.
- A mock pass is not model proof; a harness pass is not integrated MVP acceptance.
- Preserve all quality, preparation and offline conditions in §12.0.
- A hardware- or model-dependent test reports pending/not-run when its
  prerequisite is unavailable; it never passes vacuously.

## Collaboration
- Claude Code implements; ChatGPT reviews and records technical decisions in PR comments.
- Work through one consolidated review batch and report evidence against the latest SHA.
- Resolve routine choices within scope; record durable decisions in `docs/decisions/`
  with comment links.
- Do not reopen settled choices or request confirmation for routine reversible work.
- Do not change acceptance targets to make tests pass.
- Follow existing repository merge/release authorization; never infer it from a review comment.
- Keep default CI small, cancel obsolete PR runs and reserve full benchmarks for the target host.
- Batch commits locally and push one reviewable batch per review round; do not push
  after every edit or trigger Actions from comment events. Draft PRs skip the
  runner work but keep one truthful required check.

## Verified commands

Every command below was executed successfully on the development platform
recorded in `docs/verified-commands.md` (Ubuntu 24.04, CPython 3.11.15, FFmpeg
6.1.1). That file holds the observed output.

```bash
# Environment
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]" -c constraints/dev-linux-cpython311.txt

# Quick checks
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy
.venv/bin/python -m pytest -m "not slow"      # contract, failure-path, statistics
.venv/bin/python -m pytest                    # adds tiny end-to-end media tests

# The local gate: run this once when a batch is ready, then push ONE reviewable
# batch. Caches are disabled because CI checks out fresh and a stale .ruff_cache
# can hide a finding locally that CI will report.
.venv/bin/ruff check --no-cache . && .venv/bin/ruff format --no-cache --check . \
  && .venv/bin/mypy && .venv/bin/python -m pytest -q -p no:cacheprovider

# Host inventory
.venv/bin/animalite doctor
.venv/bin/animalite doctor --json
.venv/bin/python -m animalite doctor          # fallback entry point

# One small local example (no weights, no network, no private artwork)
.venv/bin/animalite fixtures generate --out-dir work/fixture
.venv/bin/animalite render --profile fixture-synthetic \
    --anchors work/fixture/fixture-two-anchor/anchors.json --workspace work/ws

# Benchmark harness against the fixtures (reports not_eligible, as it must)
.venv/bin/animalite benchmark run \
    --dataset work/fixture/dataset.json \
    --host benchmarks/hosts/development-unapproved.json \
    --targets benchmarks/targets/section-12-0-proposed.json \
    --profile fixture-synthetic --ledger work/bench/ledger --workspace work/bench/ws \
    --warm-repetitions 1 --cold-repetitions 1 --preview-repetitions 1
```

```bash
# Learned CPU path (Package B). The runtime is installed out of band; nothing is
# committed and CI never downloads it.
.venv/bin/animalite runtime fetch          # prints pinned URL + digests only
.venv/bin/animalite runtime fetch --install  # bounded, verified, atomic install
.venv/bin/animalite runtime status         # installed / verified / compatible / admitted
```

The learned render below **fails on a fresh checkout, by design**: no admission
record exists, so `animalite.admission` refuses before anything is launched
(DEC-0016). It runs only once an operator records an approved decision covering
the pinned digests and the run's purpose — see
`docs/licensing/admissions/README.md`.

```bash
.venv/bin/animalite render --profile rife-ncnn-v4.6-cpu --purpose research \
    --anchors work/fixture/fixture-two-anchor/anchors.json --workspace work/ws
```

**Qualification commands still do not exist.** A learned model can now run —
where admission permits it — but no command here produces qualification
evidence. The remaining prerequisites are:
the D-02-approved P-L host and signed §12.0 targets, the frozen 12-clip sample
with rights records, two named quality reviewers, and a signed-off licence
disposition for the model weights (DEC-0013). Until those exist the benchmark
evaluator refuses a qualifying verdict, and it is the component that decides —
not a render.
