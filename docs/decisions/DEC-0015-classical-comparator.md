# DEC-0015 — The classical warp/flow comparator is implemented in-repo

* **Status:** Accepted
* **Deciding role:** implementation
* **Affects:** §6.0 ("Evaluate a classical warp/flow baseline and one pinned
  RIFE/ncnn CPU candidate first"), MR-018, MR-016, AT-055/AT-056

## Decision

The classical comparator is **block-matching motion estimation with bilinear
warping**, written in NumPy in `animalite.media.flow` and exposed as the
`classical-warp-baseline` profile. It is **not** delegated to FFmpeg's
`minterpolate` filter, and it is **not** a new third-party dependency.

## Why a comparator exists at all

A test the learned candidate passes is evidence of learned temporal capability
only if a non-learned method *fails* it. The PR-1 review made this point about
the disc test directly: a classical motion algorithm could also pass it, so
passing alone certifies nothing.

The comparator turns "would a baseline have done this too?" from an assumption
into a measurement. Its job is to be beaten, and to make it visible when it is
not.

## Why not `minterpolate`

`minterpolate=mi_mode=mci` is a real motion-compensated interpolator and it is
already present in the FFmpeg this project binds by content hash, so it looked
like the cheaper option. Two things ruled it out.

**It does not do the job.** On a two-frame anchor pair — which is exactly the
input this system takes — it emits nothing:

```
[vost#0:0/png] No filtered frames for output stream, trying to initialize anyway.
[out#0/image2] Output file is empty, nothing was encoded
frames: 0
```

Tried both as a `concat` of two image inputs and as a two-frame image sequence.
The filter wants more stream context than an anchor pair provides.

**A baseline used as evidence must be fixed by this repository.** `minterpolate`
behaviour depends on build options and filter defaults. A comparator whose
results shift with the FFmpeg build is a poor control, and a reviewer cannot
read its algorithm out of this repository. The NumPy implementation is
deterministic, version-pinned by our own source, and auditable in place. NumPy
is already a run-time dependency, so this adds nothing to the dependency set.

## The method, and the two things that had to be right

Full-search block matching for a piecewise-constant flow field, bilinear
upsampling to per-pixel flow, bilinear backward warping of both anchors toward
the requested time, and a time-weighted blend. Flow is estimated **once per
anchor pair** and reused for every frame in the segment.

**The zero displacement is the incumbent, not a candidate.** Starting the search
from "nothing moved" and requiring an improvement margin is what stops block
matching locking onto noise. Measured on the two-anchor fixture, whose true
motion is about 2 px:

| Search | Mean estimated displacement |
| --- | --- |
| Unguarded (best match wins) | **15.29 px**, saturating the 16 px radius |
| Zero displacement as incumbent | **0.83 px** |

**The warp sign is not cosmetic.** `flow[p]` is the displacement `d` for which
`source[p] ≈ destination[p + d]`, so landing content at time `t` samples the
source at `−t·d`. Sampling at `+t·d` still produces a plausible-looking frame —
it just reconstructs about as well as a cross-fade, which is precisely the
failure a comparator must not have. Measured against a known 24 px translation:

| Method | Mean absolute error |
| --- | --- |
| Cross-fade | 75.20 |
| Motion-compensated, **wrong sign** | 74.31 |
| Motion-compensated, correct sign | **4.82** |

A 15.6× improvement over cross-fade with the sign right; a 1.0× improvement with
it wrong. `test_the_comparator_beats_a_cross_fade_on_real_motion` fails if that
regresses, which is why the assertion is a ratio against the cross-fade rather
than an absolute number.

## What it cannot do, stated rather than designed around

* **It cannot qualify.** `EngineProfile` refuses `qualification_eligible=True`
  without `learned_temporal_participation`, and there is no learned component
  here at all, so the profile could not be marked eligible even by editing its
  source. `test_the_comparator_cannot_be_marked_eligible_even_by_editing_the_profile`
  validates from a dumped dict rather than `model_copy`, because `model_copy`
  does not re-run validators and a test built on it would pass with no guard
  present.
* **Motion beyond the search radius is not found.** The estimator reports the
  zero displacement rather than the best wrong answer at the edge of its window.
* **Block size need not divide the output, and 16 does not divide 360.** The
  estimator covers whole blocks; the remainder strip at the bottom or right edge
  inherits the nearest block's flow through the upsampler's clamp. An earlier
  version required exact division and rejected the P-L output spec outright —
  caught by an end-to-end render, not by a unit test, because the unit tests all
  used geometry that happened to divide.
* **It is slow, and that is not being fixed.** Measured on the two-anchor
  fixture: 9.02 s against the fixture adapter's 0.63 s. Full search is quadratic
  in the radius. The comparator is a quality reference, not a latency candidate;
  §12.0 latency targets apply to the qualifying profile, and optimising the
  baseline would only make the control harder to reason about.

## Consequences

* Package B now carries both halves §6.0 asks for: the pinned learned candidate
  (DEC-0011/0012) and this baseline.
* Any future claim that the learned candidate demonstrates temporal capability
  can be checked against the baseline on the same clips, rather than against a
  cross-fade that MR-018 already excludes.
* The comparator adds no weights, no binaries, no network access and no
  third-party licence question. `weights` and `binaries` on its profile are
  deliberately empty.
