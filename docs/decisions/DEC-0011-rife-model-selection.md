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
| `rife-anime` | 170.40 | 158.89 | 158.89 | **explanation unverified — see below** |

### Correction: the "it fails silently" explanation does not hold

An earlier version of this record said the critical property was that
`rife-anime` **does not fail** — that it returns a well-formed but temporally
wrong frame. The pinned wrapper contradicts that. In
[`main.cpp` at the pinned commit](https://github.com/nihui/rife-ncnn-vulkan/blob/a7532fc3f9f8f008cd6eecd6f2ffe2a9698e0cf7/src/main.cpp#L685):

```c
if (!rife_v4 && (numframe != 0 || timestep != 0.5))
{
    fprintf(stderr, "only rife-v4 model support custom numframe and timestep\n");
    return -1;
}
```

A non-v4 model with a non-0.5 timestep **exits −1 and writes no output**. So the
binary refuses; it does not return a wrong frame.

The `rife-anime` row above is therefore recorded as **unverified**. The exact
binary path, model digests, argv and exit status from that run were not
retained, so the reading cannot be reconstructed. The repeated 158.89 is
consistent with the tool having refused and the measurement having read a stale
or duplicated output file, but that is a hypothesis, not a finding, and no
further model experiment is being run to repair prose.

The decision is unaffected, and rests on two things that are checkable now:

* the architecture is midpoint-only, which the 72-frame contract cannot use;
* the pinned binary refuses the combination outright, so the failure mode is a
  mid-render subprocess error rather than a validation message — which is
  exactly why the rejection belongs in `validate()`, before anything runs.

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
