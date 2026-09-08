# AnimaLite

**Status: Package B in progress — one learned CPU model (RIFE via ncnn) is now
integrated behind the common adapter interface. No §12.0 performance target has
been measured on an approved host, and no qualification has been attempted.**

AnimaLite is the implementation of the *Frame-Conditioned 2D AI Video Production
System* requirements (v0.12). Its objective is to produce a short, useful video
clip from 2–4 approved frames on CPU or lower-spec hardware, with a measured and
honestly reported turnaround.

This repository currently contains the foundation for that work: typed contracts,
a local execution service, a CPU media pipeline, a host inventory command, a
benchmark harness, and a deterministic **fixture** adapter used to exercise the
pipeline end to end without any model weights or private artwork.

## What works today

| Capability | State |
| --- | --- |
| Installable `animalite` package and CLI (`animalite`, `python -m animalite`) | Working |
| Typed, versioned contracts (anchors, shot intent, engine profile, job/attempt, capabilities, resource estimate, output manifest, measured results, host inventory) | Working |
| Local execution service with the §6.3 lifecycle (validate / estimate / submit / status / cancel / collect / capabilities) | Working |
| Immutable attempt directories, finite timeouts, process-group cleanup, retained failure diagnostics, retry-as-new-attempt | Working |
| CPU media pipeline: anchor decode, cadence expansion, streaming CPU encode, decode validation before publish | Working |
| Reproducible synthetic fixture generator and fixture adapter (deterministic, **not** learned) | Working |
| Host/environment inventory (`animalite doctor`) | Working |
| Benchmark harness: run ledger, stage/end-to-end timing, process-group memory where supported, median / nearest-rank p95 / maximum, failed-and-missing-run retention, qualification eligibility evaluator | Working |
| Learned CPU temporal model (`rife-ncnn-v4.6-cpu`, CPU-only) | Working — runtime installed out of band and hash-verified |
| Classical warp/flow comparator | **Not implemented** — Package B |
| §12.0 qualification measurements (AT-055 / AT-056) | **Not run** — Package C, and blocked on the D-02 host approval |
| Web/review UI, project storage, queue, export, cloud or GPU execution, training | **Out of scope** for this stage |

## What this repository does *not* claim

* **No qualified learned-model performance has been demonstrated.** A learned
  model now runs, and its output is measurably real temporal synthesis rather
  than a cross-fade — but that is an engineering result, not a §12.0 result.
  `fixture-synthetic` remains a deterministic anchor blend and is labelled
  non-qualifying everywhere; MR-018 excludes cross-fades from learned temporal
  capability. A learned render is *also* not qualification evidence on its own,
  and its manifest says so with the actual reasons.
* **The model's licence position is recorded as unresolved.** RIFE's code and
  weights are both MIT upstream, but the ncnn-format conversion chain has not
  been reviewed, so the profile is `use_eligible: false` and the benchmark
  evaluator blocks qualification. Development is unaffected. See
  `docs/decisions/DEC-0013-rife-licence-position.md`.
* **No timing here is a P-L result.** Section 12.0's warm/cold/preview targets
  are *proposed* engineering targets awaiting D-02 approval. Any number produced
  on a developer or hosted machine is exploratory. The benchmark evaluator
  refuses to emit a qualifying verdict when the host is unapproved, the adapter
  is non-learned, an observation is missing, or human quality evidence is absent.
* **No phase gate has passed.** Phase 0 (D-01/D-02) and the Phase 1 CPU
  feasibility gate remain open.

## Requirements and prerequisites

* Python 3.11–3.13 (development baseline: CPython 3.11).
* An **externally installed** FFmpeg providing `ffmpeg` and `ffprobe` on `PATH`
  (or pointed at by `ANIMALITE_FFMPEG` / `ANIMALITE_FFPROBE`). FFmpeg is not
  bundled or vendored here; see `THIRD_PARTY_NOTICES.md` and `docs/licensing.md`.
* No GPU and no network access at run time.
* The **fixture** profile needs no weights. The **learned** profile needs the
  pinned RIFE/ncnn runtime, installed out of band — nothing is committed and CI
  never downloads it. Run `animalite runtime fetch` for the pinned steps and
  `animalite runtime status` to confirm the digests verify.

## Install and verify

See [docs/verified-commands.md](docs/verified-commands.md) for the exact commands
that were executed for this branch, with their observed output.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]" -c constraints/dev-linux-cpython311.txt

animalite --help
animalite doctor --json          # host + tool inventory; inventory, not approval
python -m animalite doctor       # equivalent fallback entry point
```

## One small local example

Generate the deterministic synthetic anchors, then render them through the real
CPU media path:

```bash
animalite fixtures generate --out-dir work/fixture --clip fixture-two-anchor
animalite render \
  --profile fixture-synthetic \
  --anchors work/fixture/fixture-two-anchor/anchors.json \
  --workspace work/ws \
  --json
```

The result is a 640×360 H.264/MP4 file: 72 animation frames at 12 animation fps,
expanded by two-frame holds into 144 delivery frames at 24 fps — exactly 6.000
seconds. The published manifest records the source, synthesized and duplicated
frame counts separately, and carries
`is_qualifying_evidence: false`.

`--profile` is mandatory: rendering never selects an engine implicitly, so a
fixture render can never be mistaken for the future learned model.

## Quick check

```bash
ruff check . && ruff format --check .
mypy
pytest -m "not slow"        # contract, failure-path and statistics tests
pytest                      # adds the tiny end-to-end media integration test
```

Media tests report *pending* rather than passing when FFmpeg is unavailable.

## Repository layout

```
src/animalite/contracts/   typed, versioned job/profile/asset/result contracts
src/animalite/errors.py    exception hierarchy and stable validation codes (leaf)
src/animalite/proc.py      child-process group management (leaf)
src/animalite/resources.py thread budget and peak-memory sampling (leaf)
src/animalite/core/        validation, execution service, attempt store
src/animalite/adapters/    adapter protocol, fixture (non-learned) and RIFE/ncnn (learned) adapters
src/animalite/media/       ffmpeg discovery, cadence, streaming encode, probe validation
src/animalite/bench/       benchmark runner, ledger, statistics, eligibility evaluator
src/animalite/hostinfo/    host and tool inventory
benchmarks/                dataset manifests, host records, target sets, evidence bundles
docs/requirements/         the v0.12 source document and a labelled CPU-stage extract
docs/decisions/            durable implementation decisions
docs/verification/         requirement / AT / evidence mapping
```

## Licensing

AnimaLite's own source code is licensed under the
[PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0)
(SPDX: `PolyForm-Noncommercial-1.0.0`). The complete, unmodified license text is
in [`LICENSE`](LICENSE).

AnimaLite is **source-available**, not OSI open source: a commercial-use
restriction does not meet the
[Open Source Definition](https://opensource.org/osd). PolyForm Noncommercial
permits noncommercial purposes and certain organizational uses, including
educational and government institutions irrespective of funding; it is not an
absolute prohibition on every revenue-related activity. Read the license text
rather than this summary.

This license covers **only** the original AnimaLite software in this repository.
Third-party dependencies, the separately installed FFmpeg, and any model code or
weights added later keep their own terms — recorded in
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) and discussed in
[`docs/licensing.md`](docs/licensing.md).

**Commercial permission** is a project-owner decision. Requests are made by
opening a GitHub issue in this repository titled `Commercial use request`; no
contact address, price or standard commercial terms exist yet, and none is
implied here. The maintainer cannot unilaterally relicense contributions made by
others, so any commercial arrangement needs legal review — see
[`CONTRIBUTING.md`](CONTRIBUTING.md).

The copyright-holder name in [`NOTICE`](NOTICE) is an open metadata item
(`<COPYRIGHT-HOLDER-PENDING>`), deliberately left for the owner to supply.

## Working agreement

Engineering and review instructions live in [`AGENTS.md`](AGENTS.md);
[`CLAUDE.md`](CLAUDE.md) imports them. Durable implementation decisions are
recorded in [`docs/decisions/`](docs/decisions/).
