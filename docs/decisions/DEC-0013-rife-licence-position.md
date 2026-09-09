# DEC-0013 — RIFE/ncnn licence position

* **Status:** Recorded as **unresolved**; disposition is an owner/legal decision
* **Deciding role:** implementation (evidence) → owner + legal reviewer (disposition)
* **Affects:** C-04, MR-012, MR-014, CR-024, D-06

## What was verified

From primary sources, not repository badges (handoff §0: *"a model repository's
top-level badge is not enough"*):

| Component | Licence | Evidence |
| --- | --- | --- |
| `rife-ncnn-vulkan` wrapper code | MIT | repo `LICENSE`, sha256 `a73beab18143600a…` |
| `ncnn` runtime | BSD-3-Clause | Tencent `LICENSE.txt`, sha256 `7c974bac98848df4…` |
| RIFE **trained models** | **MIT** | Practical-RIFE `README.md`, *"### Trained Model — The content of these links is under the same MIT license as this project."* |
| ECCV2022-RIFE (research repo) | MIT | `LICENSE`; *"According to the open source license, we respect the commercial behavior of other developers."* |

**This contradicts the widespread assumption** that RIFE is
non-commercial-research-only. Current upstream licenses the **weights**
explicitly, in a statement separate from the code licence — which is exactly the
code/weight separation MR-012 and handoff §0 require. No non-commercial
restriction was found in any of the four documents checked.

## What is *not* resolved

The weights AnimaLite actually loads are **ncnn-format conversions** shipped in
nihui's release, not the upstream `.pkl` checkpoints. That repository's README
does not restate weight terms. The chain is therefore:

```
rife-ncnn-vulkan repo LICENSE (MIT, covers repo contents)
  + upstream RIFE's explicit MIT statement for trained models
  => converted weights are MIT
```

That is a reasonable reading. It is also a derivation **across two projects**,
made by an implementer, and MR-012 requires derived-model obligations to be
reviewable before use. So it is recorded as evidence, not concluded.

## Decision

The profile carries a `LicenseEvaluation` with:

```
policy_state:            pending
use_eligible:            false
eligibility_block_kind:  resolvable
```

which is the CR-024 mapping for *"pending, unknown or unmet evidence"*. Effects:

* **development and benchmarking proceed** — validation emits
  `VAL-LICENCE-NOT-CLEARED` as a *warning*, so the adapter is fully usable for
  engineering work;
* **qualification is blocked** — the benchmark evaluator emits a blocking
  `ELIG-LICENCE-NOT-CLEARED` finding, so no §12.0 pass can be reported while the
  position is unresolved. A profile with *no* licence evaluation at all is
  blocked by `ELIG-LICENCE-MISSING`.

`eligibility_block_kind: resolvable` — not `hard` — because nothing found
suggests the use is prohibited; the evidence chain simply needs confirming.

## What the reviewer needs to decide

1. Does the MIT statement covering the linked model downloads extend to the
   ncnn-format conversions redistributed in the `rife-ncnn-vulkan` release?
2. Does D-06 (permissive-only production, or custom community licences allowed)
   admit this stack? On the evidence above it is permissive throughout, so this
   should be straightforward — but D-06 is unsigned, and MR-014 makes production
   use conditional on it.
3. Are the retained notices sufficient? Nothing is vendored: the runtime is
   installed out of band by the operator and no third-party file is committed,
   so AnimaLite currently redistributes none of it.

Until answered, `use_eligible` stays `false`. Flipping it is a one-field change
plus the reviewer's identity and date.
