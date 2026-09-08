# DEC-0011 — RIFE model selection and the timestep safety rule

* **Status:** Accepted
* **Deciding role:** implementation
* **Affects:** MR-018, MR-016, §9.1 ("checkpoint/runtime compatibility must be pinned")

## Decision

The pinned learned CPU candidate is **`rife-v4.6`**, from the
`rife-ncnn-vulkan 20221029-ubuntu` release. **`rife-anime` is declared but
excluded from use**, and any midpoint-only model combined with a non-0.5
timestep is **rejected at validation** rather than executed.

## Why `rife-anime` is excluded despite fitting the project's art style

The project is stylized 2D (C-01), so an anime-tuned checkpoint looks like the
obvious choice. It is not usable here, and the reason is a measurement.

`rife-anime` is a v2-era model (flownet + contextnet + fusionnet): a **2x
midpoint** model. `rife-v4.6` is the v4 architecture (flownet only) and takes a
timestep. Asked for t = 0.25 / 0.50 / 0.75 between two anchors 40.88 px apart:

| model | t=0.25 | t=0.50 | t=0.75 | |
| --- | --- | --- | --- | --- |
| `rife-v4.6` | 149.29 | 159.84 | 170.40 | monotonic; expected 149.1 / 159.3 / 169.6 |
| `rife-anime` | **170.40** | 158.89 | 158.89 | **non-monotonic — the subject moves backwards** |

The critical property is that `rife-anime` **does not fail**. It returns a
well-formed, plausible-looking frame that is temporally wrong. Nothing
downstream — decode validation, frame accounting, duration checks — would catch
it, because every one of those checks passes. Only comparing against known
motion reveals it.

Section 12.0 needs frames at arbitrary animation indices (frame *k* between
anchors *i* and *j* is at t = (k−i)/(j−i)), so a midpoint-only model is
categorically wrong for the 72-frame contract. It is left declared in
`PINNED_MODELS` with `supports_arbitrary_timestep=False` and **no pinned
digests**, specifically so that selecting it produces an explicit rejection
rather than a silent substitution.

## Enforcement

`RifeNcnnAdapter.validate` computes the timesteps the request will actually
need and emits `VAL-RUNTIME-TIMESTEP-UNSUPPORTED` when a midpoint-only model
would be asked for any of them. The rule is about the *timesteps needed*, not
the model alone: a 3-frame output with anchors at 0 and 2 needs only t=0.5 and
is allowed, which a test asserts so the rule is not overly broad.

## Reversal

Reinstating `rife-anime` would require pinning its digests and restricting it to
exact-midpoint work. The 72-frame quick-clip contract does not reduce to that,
so this is not a near-term option. A different anime-tuned **v4** checkpoint
would be a straightforward substitution: add it to `PINNED_MODELS` with
`supports_arbitrary_timestep=True`, its digests, and re-run the ramp check.
