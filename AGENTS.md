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
- Use one classical comparator; it cannot satisfy learned temporal capability.
- Keep UI, episode services, cloud/GPU branches and training outside the first proof.
- Missing hardware evidence leaves qualification pending; continue useful coding.

## Coding
- Keep domain contracts independent of native model libraries. `animalite.core`
  and `animalite.contracts` must not import a model runtime; adapters are reached
  only through `animalite.adapters.registry.Registry`.
- Use typed, versioned schemas; make units, frame indexing and device policy explicit.
  Every contract sets `extra="forbid"`: an unknown field is an error, not a
  dropped value.
- Stream frames with bounded memory; pin total threads and batch size.
- Retain immutable attempts, failure diagnostics and safe process cleanup. A
  retry creates a new attempt linked to its parent; it never rewrites one.
- Use explicit CPU runtime/encoder selection; never silently fall back remotely.
- Invoke native tools with argument arrays, never a shell string.
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

**Model-dependent and qualification commands do not exist yet.** No command in
this repository downloads weights, runs a learned model, or produces
qualification evidence. The prerequisites for those are: an integrated learned
CPU adapter with verified code/weight licenses (Package B), the D-02-approved
P-L host and signed §12.0 targets, the frozen 12-clip sample with rights records,
and two named quality reviewers (Package C).
