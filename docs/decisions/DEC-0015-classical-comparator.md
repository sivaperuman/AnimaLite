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

**Corrected after PR-2 review (B-R7).** An earlier version of this record said a
test is evidence of learned capability "only if a non-learned method *fails*
it". That rule is wrong, and it points at a bad incentive: it would make
weakening the comparator a way to manufacture evidence.

The accurate statement: when a classical method passes the same example, that
does not negate verified learned participation. It means *that example* cannot
identify the mechanism or establish a learned advantage — the observation is
consistent with both, so it discriminates between neither.

The comparator therefore exists to turn "would a baseline have done this too?"
from an assumption into a measurement, on the same inputs and within the same
resource envelope. It is meant to be a **credible reference**, and the useful
outcome is a fair comparison, not a win. A comparator built to lose would tell
us nothing at all.

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
* **Motion beyond the search radius is reported wrongly, not as zero.** An
  earlier version of this record claimed the zero incumbent made out-of-range
  motion report no motion. It does not, and PR-2 review demonstrated it: on a
  deterministic 64×96 random texture translated 24 px and searched at radius 4,
  **95 of 96 blocks returned nonzero flow**. Reproduced here exactly. The zero
  incumbent only helps where there is nothing to match — a flat or near-flat
  region — because on texture some within-window candidate almost always beats
  standing still, and it is accepted.

  What the estimator does guarantee is the *bound*: no reported displacement
  exceeds the search radius. That is a much weaker property than detection, and
  the two are now asserted by separate tests so they cannot be conflated again.
  More generally, block matching is a local minimisation with no notion of
  correctness: repeating texture and occlusion produce confident wrong answers
  too, and nothing in the output distinguishes them from good matches.
* **Block size need not divide the output, and 16 does not divide 360.** The
  estimator covers whole blocks; the remainder strip at the bottom or right edge
  inherits the nearest block's flow through the upsampler's clamp. An earlier
  version required exact division and rejected the P-L output spec outright —
  caught by an end-to-end render, not by a unit test, because the unit tests all
  used geometry that happened to divide.
* **It is slow.** Measured on the two-anchor fixture: 9.02 s against the fixture
  adapter's 0.63 s (single runs, development container, exploratory). Full
  search is quadratic in the radius. §12.0 latency targets apply to the
  qualifying profile, so this does not disqualify the comparator as a quality
  reference — but "assess it fairly on the same inputs and resource envelope"
  (PR-2 review) means its cost is reported alongside the learned candidate's
  rather than excused. It is bounded like everything else: the search now calls
  a cooperative checkpoint once per displacement row, so cancellation and the
  job deadline interrupt it part-way instead of waiting out the whole search.

## Consequences

* Package B now carries both halves §6.0 asks for: the pinned learned candidate
  (DEC-0011/0012) and this baseline.
* Any future claim that the learned candidate demonstrates temporal capability
  can be checked against the baseline on the same clips, rather than against a
  cross-fade that MR-018 already excludes.
* The comparator adds no weights, no binaries, no network access and no
  third-party licence question. `weights` and `binaries` on its profile are
  deliberately empty.
