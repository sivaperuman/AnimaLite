# Benchmark harness inputs

This directory holds the *inputs* to the benchmark harness. Run outputs
(ledgers, reports, encoded media) are written elsewhere and are git-ignored;
only manifests, host records, target sets and checksums are versioned.

| Path | Contents |
| --- | --- |
| `datasets/` | Dataset manifests. `qualification-sample.template.json` documents the shape of the section 12.0 locked 12-clip sample and contains no clips. |
| `hosts/` | Host records. `development-unapproved.json` is the default: **not** D-02 approved. |
| `targets/` | Target sets. `section-12-0-proposed.json` transcribes the section 12.0 proposed limits with `approved: false`. |
| `evidence/` | Evidence bundles (quality reviews, fresh-input packs, unsupported cases, continuous workload, offline/device status). Empty means missing, which blocks qualification. |

## What the evaluator will refuse

`animalite benchmark run` always produces a report. It emits
`verdict: qualifying_pass` only when *every* one of these holds:

* the engine profile is qualification-eligible (a learned component participates
  in temporal synthesis — MR-018);
* the host record carries a D-02 approval, an inventory and a recorded
  power/thermal policy;
* the target revision is approved;
* the dataset is `purpose: qualification`, `locked: true`, composed 4 / 4 / 4 by
  category, with at least two two-anchor clips;
* the plan schedules exactly the dataset's clips at batch size one with 3 warm,
  1 process-cold and 3 warm-preview repetitions per clip;
* every planned run has a record, and every record succeeded;
* every successful run carries a measured application-group peak-memory
  observation within the limit;
* the ledger hash chain verifies;
* two independent reviewers scored every clip ≥ 8/10 on identity and motion with
  no zero dimension and no severity-2/3 defect;
* the four AT-056 fresh-input packs, the four unsupported cases, the continuous
  20-minute workload, the offline rerun and the runtime/device trace are all
  present.

Anything missing yields `not_eligible` and a report labelled
**EXPLORATORY — NOT QUALIFICATION EVIDENCE**.

## Running the harness against the fixtures

```bash
animalite fixtures generate --out-dir work/fixture
animalite benchmark run \
  --dataset work/fixture/dataset.json \
  --host benchmarks/hosts/development-unapproved.json \
  --targets benchmarks/targets/section-12-0-proposed.json \
  --profile fixture-synthetic \
  --ledger work/bench/ledger \
  --workspace work/bench/ws \
  --warm-repetitions 1 --cold-repetitions 1 --preview-repetitions 1
```

That command exercises the whole harness and will report `not_eligible` — as it
must, because the profile is a non-learned fixture and the host is unapproved.
