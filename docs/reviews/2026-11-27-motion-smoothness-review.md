# Motion smoothness review: why characters read as "zombies", and how to get to Pixar-style 2D motion

* **Date:** 2026-11-27
* **Reviewed commit:** `666a555` (`main`, merge of PR #4), working tree clean
* **Scope:** every path in this repository that produces character motion, judged on
  *motion quality* (timing, arcs, weight, overlap, holds), not on throughput or on the
  §12.0 qualification contract. Nothing here changes a target, a decision record or
  the admission rules; where a suggestion needs an owner decision it says so.
* **Status of the suggestions:** proposals. Numbers labelled *measured* were produced on
  this development container during the review (not a P-L host). Numbers from decision
  records are cited as such. Every third-party model or tool is listed with its licence
  position as found on 2026-11-27 and must be re-verified against the LICENSE file
  before any admission decision (DEC-0016).

---

## 1. Summary

The "zombie" look has one dominant cause and several contributing ones.

**Dominant cause: motion is produced by constant-velocity, pixel-space interpolation
between two or three widely spaced drawings.** On the sparse-anchor path (`rife-ncnn-v4.6-cpu`
and `classical-warp-baseline`) every pixel of the character travels in a straight line at
constant speed from pose A to pose B, starts moving at full speed on the first frame, stops
dead on the last, and arrives everywhere at once. That is the textbook signature of
mechanical motion: no slow-in/slow-out, no arcs, no anticipation, no overlap, no
follow-through, no moving holds. A frame interpolation model cannot add those; it only
fills the gap it is given. When the gap is a 1–3 second pose change in artwork that is not
registered, RIFE additionally produces the melting limbs and ghosted edges that make a
figure look undead.

**Contributing causes, in order of impact:**

| # | Finding | Where | Effect on screen |
| --- | --- | --- | --- |
| F1 | Linear timestep only; the learned profile rejects any `timing` control | `adapters/rife_ncnn.py`, `story.py` | Robotic constant speed, hard starts and stops |
| F2 | One global easing curve for the whole frame | `adapters/classical_warp.py`, `blender_cinema.animate` | Everything moves and lands on the same frame ("twinning") |
| F3 | Straight-line paths for hands, head and eye targets | `blender_blocking.Blocking.resolve` (`lerp`) | Mechanical reaches; nothing swings |
| F4 | No overlap, follow-through, overshoot or settle | all rigged paths | Poses land like an elevator stopping |
| F5 | Dead holds: a held pose is a frozen frame | story poses repeated at two indices; `animate()` first/last hold; 12→24 duplication | Character "dies" between actions |
| F6 | Pixel interpolation asked to bridge large pose changes | README "it can ghost on large changes"; DEC-0011 ramp was 40.88 px | Melting limbs, double edges, disappearing hands |
| F7 | Instant state changes in the rig | finger curl `-0.95 if closed else 0.10` in `blender_blocking.bake` | One-frame pops |
| F8 | No procedural "life" layer in the 3D stage | `blender_cinema.animate` | No breathing, no idle blink, no weight shift unless authored |
| F9 | No motion-quality metric in review tooling | `spikes/studio_s1/take_review.py` checks stillness and black frames only | Smoothness regressions are invisible until a human watches |

The best-looking motion in the repository is the hand-coded harbour demo
(`examples/harbour/draw.py`): it has phase-locked walk and run cycles, a torso bounce tied
to foot contact, lean that anticipates the run, quintic easing, breathing, scheduled
blinks, a hand that opens over several frames and an elbow that leads the wrist. It
demonstrates every principle the other paths lack, and it is the right reference for
what to generalise.

**Recommendation in one line:** keep learned interpolation for what it is good at (small
gaps, secondary motion, final polish) and move character *performance* onto a rigged,
curve-driven layer with a procedural life layer on top. Section 5 gives the plan, section 6
the open-source building blocks.

---

## 2. What was reviewed

| Path | Files | Role |
| --- | --- | --- |
| Sparse-anchor interpolation (learned) | `src/animalite/adapters/rife_ncnn.py`, `rife_runtime.py`, DEC-0011, DEC-0012 | RIFE v4.6 via ncnn, one subprocess per synthesized frame, explicit `-s` timestep |
| Sparse-anchor interpolation (classical) | `src/animalite/adapters/classical_warp.py`, `src/animalite/media/flow.py`, DEC-0015 | Block matching + bilinear warp + blend, optional `ease-in-out` |
| Cadence | `src/animalite/media/cadence.py`, DEC-0005 | 12 animation fps, two-frame holds to 24 fps |
| Story renderer | `src/animalite/story.py`, `story_media.py` | Pose images at animation indices, zoom, dialogue, hard cuts |
| 3D stage and acting | `src/animalite/blender_stage.py`, `blender_cinema.py`, `blender_blocking.py`, `performance.py`, `choreography.py`, `performance_moves.json` | Ellipsoid cast, acting poses, two-link IK, prop contacts |
| 2D procedural demos | `examples/harbour/draw.py`, `spikes/studio_s1/performance.py` | Cairo / resvg / Godot cut-out rigs |
| Evidence | `docs/verification/studio-s1/*.webp`, `STUDIO-S1-rig-feasibility.md` | S1 contact sheet and preview |

Commands run for this review are in Appendix A.

---

## 3. Evidence

### 3.1 The interpolation path moves at constant speed (measured)

The two-anchor fixture was rendered through `classical-warp-baseline` with `linear` timing
and with `ease-in-out`, decoded to RGB and the mean absolute difference (MAD) between
consecutive *animation* frames was computed as a proxy for on-screen velocity. The fixture
motion is only about 2 px, so the absolute values are small and noisy under H.264, but the
shape is unambiguous:

| Timing | Velocity by tenth of the clip (MAD per animation step) | First step | Last step |
| --- | --- | ---: | ---: |
| linear | 0.124 0.102 0.112 0.111 0.118 0.115 0.110 0.108 0.114 0.123 | 0.110 | 0.094 |
| ease-in-out | 0.036 0.122 0.118 0.150 0.159 0.148 0.149 0.121 0.111 0.035 | 0.001 | 0.001 |

Linear: the character is already at full speed on frame 0→1 and still at full speed on
frame 70→71. That is the hard start / hard stop. Ease-in-out fixes the ends but is a single
symmetric curve applied to the whole frame: every pixel accelerates and decelerates
together, which is why eased interpolation still reads as "smooth but robotic" rather than
alive.

The RIFE adapter cannot even do that much. `animalite render --profile rife-ncnn-v4.6-cpu
--control timing=ease-in-out` reports:

```
[VAL-CONTROL-UNSUPPORTED] the RIFE adapter does not implement control 'timing'
```

so a storyboard with `"timing": "ease-in-out"` fails validation on the learned profile
(`story.py` passes it straight through as a control). The learned path is linear only.

### 3.2 The interpolation path is asked to bridge gaps it was not trained for

RIFE v4.6 is trained on consecutive real-video frames (Vimeo90K-style triplets): small
displacements, photographic texture, consistent lighting. The story workflow feeds it two
image-generator outputs 1–3 s apart with a pose change of tens to hundreds of pixels at
640×360 and no guarantee that line weight, proportions or lighting match. DEC-0011's own
ramp check used a 40.88 px subject shift; the README states the baseline "can ghost on
large changes". Between a pose with an arm down and a pose with an arm raised the model has
to invent the whole arc of the arm from two flow fields; what it returns is a crossfade
with warped edges, i.e. a limb that dissolves and re-forms. That *is* the zombie limb.

The 12 fps animation cadence with two-frame holds (CR-004, DEC-0005) is not itself the
problem; animating "on twos" is standard 2D practice. It only becomes steppy when combined
with linear timing and large per-frame displacement, which is exactly the current
combination.

### 3.3 The rigged stage moves correctly but not expressively

`blender_cinema.animate()` interpolates every acting channel (head turn, tilt, gaze, brow,
smile, blink, raise_hand, squash) with the same smoothstep `u` between the same two poses.
`blender_blocking` improves on this with per-track beats, but each beat is still a
smoothstep from the previous value to a destination, hand and head targets are resolved by
`origin.lerp(end, factor)` in world space (a straight line), the fingers switch between two
rotations in one frame, and nothing moves unless a beat says so. The S1 cut-out rigs
(`spikes/studio_s1/performance.py`) are better: they add sway, bounce, a breathing term and
a toe-drop on the swing foot, and the contact sheet shows readable poses. Their limitation
is that every one of those terms is hand-written per shot.

### 3.4 What the harbour demo gets right (the internal reference)

`examples/harbour/draw.py` is worth reading as a specification for the motion layer:

* **Timing:** quintic easing (`ease5`) and a trapezoidal distance profile (`distprog`)
  for travel, so the root accelerates and decelerates over a stated distance.
* **Locomotion:** a shared stride phase drives feet, hip bounce (`push`), arm swing and
  head tilt; the foot path is an arc with heel tuck and toe-open (`feet()`).
* **Anticipation and settle:** `anticip` and `settle` gates lean the body before the run
  starts and after it stops.
* **Overlap:** the elbow leads the wave and the wrist lags (`swingW` phase offsets);
  the hand opens over several frames (`handdraw` spread).
* **Life:** `breathe`, scheduled blinks, a head bob while speaking.

Those are the twelve principles in code form. They are currently reachable only by writing
Python per shot.

---

## 4. Root-cause analysis against the animation principles

| Principle | Interpolation path | 3D stage | Harbour demo | Consequence when missing |
| --- | --- | --- | --- | --- |
| Slow in / slow out | none (RIFE), global only (classical) | smoothstep | quintic + trapezoid | hard starts/stops |
| Arcs | none (straight flow) | none (lerp) | yes | robotic reaches |
| Anticipation | only if the artist draws a key | only if authored | yes | actions have no "wind-up" |
| Follow-through / overlap | none | none | partial | everything stops together |
| Secondary action | none | none | hair/head bob | stiff |
| Moving holds | none (frozen duplicates) | none | breathing | character dies between beats |
| Squash & stretch | none | root scale only | torso push | no weight |
| Timing variety | one curve | one curve per beat | per-term | monotonous rhythm |
| Appeal / solid drawing | depends on generator | ellipsoids | drawn | n/a to motion |

The pattern is the same everywhere: timing is a property of the *whole* transition, never
of an individual body part, and transitions are symmetric. Living motion is asymmetric
(fast out, soft in), staggered across parts, and never fully still.

---

## 5. Improvement plan

Ordered by expected visible improvement per unit of work. Items 5.1–5.4 need no new
dependency, no weights and no owner decision. 5.5–5.7 need a decision or an admission.

### 5.1 Timing layer for the interpolation path (small, immediate)

Add a shared timing module (for example `animalite.media.timing`) used by *both*
adapters, so the request's `timing` control is honoured identically:

* curves: `linear`, `ease-in`, `ease-out`, `ease-in-out` (smoothstep), `quintic`,
  `cubic-bezier(x1,y1,x2,y2)` (what animators actually tune), `overshoot(k)`
  (back-ease: pass the target by `k` and return), `anticipate(k)` (move away first);
* a `hold_in`/`hold_out` in frames so a key can be held *without* duplicating a source
  image at two indices, which currently is the only way to hold and produces a dead still;
* the RIFE adapter maps the eased phase onto `-s`, so `timing` becomes a supported control.
  It still synthesises one unique frame per animation index, so the frame-index contract
  and the source/synthesized/duplicated accounting are untouched; only the *content* of
  frame *k* changes. The timing value must enter the settings digest and the manifest.

Boundary to state in the decision record: the §12.0 qualification sample should be run
with `linear` unless the owner approves otherwise, because the proposed targets were
written against uniform sampling. Creative renders are free to ease.

### 5.2 Key-spacing budget and pre-flight check (small)

Make "the gap is too big for the interpolator" a validation finding instead of a ghosted
render:

* run `media.flow.estimate_block_flow` between each adjacent anchor pair at validation
  time (it exists, it is CPU-only, and it is already bounded by the job deadline);
* report mean and 95th-percentile block displacement per pair in the manifest;
* warn above a *proposed* threshold (start at the 2.60 px per-frame figure DEC-0012 measured
  as good and the 40.88 px total DEC-0011 ramped cleanly, i.e. roughly 1 px per animation
  frame; label it proposed until measured on real poses);
* document the workflow rule in README: a pose change bigger than the budget needs a
  breakdown drawing (anticipation, contact, overshoot) from the image generator, not a
  longer interpolation. This is the MR-018 "unsupported action must be rejected or sent for
  explicit redesign" clause applied to motion size.

### 5.3 Procedural life layer for the rigged stage (medium, highest visual payoff)

Add, in `blender_cinema`/`blender_blocking`, a post-process over every channel that is
independent of what the storyboard authored:

* **Overlap by filtering.** Run each channel through a critically damped second-order
  filter (`y'' = k(x - y) - 2√k·y'`) with a different `k` per body part: pelvis stiffest,
  spine softer, head softer still, hands softest, props softest. Children automatically lag
  parents and settle with follow-through. One parameter per part replaces hand-authored
  delays, and the existing `peek` move ("eyes at 1–4, head at 7–15, body at 11–19") becomes
  the default behaviour rather than something every move must encode.
* **Arcs.** Resolve hand and head targets through a quadratic Bezier whose control point is
  offset along the up-vector by a fraction of the travel distance, instead of `lerp`.
* **Asymmetric easing.** Default beats to ease-out-heavy curves (fast leave, soft arrive),
  with `overshoot` available per beat for comedy.
* **Moving holds.** Always-on breathing on the spine and head (period 3–4 s, 1–2 % of
  height), a blink scheduler (random 2–6 s with a 3-frame close / 5-frame open), and a
  micro weight shift on the pelvis. Amplitudes small enough to be invisible as motion but
  large enough that no frame equals its neighbour.
* **Finger curl over frames.** Replace the one-frame flip with a 4–6 frame eased curl that
  starts before contact.
* **Squash and stretch on limbs.** Stretch a limb along its direction by a function of its
  speed (with volume preservation, as the root already does), and add a smear or motion
  blur on frames whose displacement exceeds a threshold (`cinema.shutter` already exists;
  expose a per-shot default).

Every term above is deterministic and seedable, so the attempt remains reproducible.

### 5.4 Motion-quality measurement in review (small)

Extend the take review to record, per shot:

* per-frame mean flow magnitude (the existing block-flow estimator is enough) and its
  first and second differences (acceleration, jerk);
* a **hard-start / hard-stop** flag when velocity on the first or last step of a segment
  exceeds half the segment peak;
* a **synchrony** score: fraction of the frame's moving blocks whose peak-velocity frame
  coincides, which detects "everything moves together";
* a **dead-hold** detector that distinguishes an intentional hold with life (small nonzero
  motion) from a frozen duplicate;
* an established smoothness metric such as SPARC or log-dimensionless jerk on the root
  trajectory, reported, not thresholded.

These are *measurements* for the Studio rubric (STUDIO handoff §9), not acceptance
targets, and they must not be mistaken for the §12.0 human quality score.

### 5.5 Character performance from a rig, not from pixels (medium to large; needs the S2–S4 decision)

For character acting the project should stop asking the interpolator to invent motion.
Two feasible shapes, both consistent with the Studio handoff:

* **Cut-out rig from the generated artwork.** Segment the character from each generated
  pose into layers (head, torso, upper/lower arm, hand, upper/lower leg, foot), build a
  2.5D rig, and drive it from motion clips. Meta's *Animated Drawings* (section 6) does
  exactly this on CPU from a single image: mask, joint annotation, ARAP mesh deformation and
  BVH retargeting with a frontal/sagittal projection. It is the fastest route from "one
  ChatGPT drawing of Milo" to "Milo walks with weight".
* **Motion from a prior, not from keys.** Walk, run, wave, turn, jump and reaction clips
  can come from mocap (CMU) or a text-to-motion model (MDM / MoMask, CPU-feasible) and be
  retargeted to the 2D rig. The output has natural arcs, weight shift and overlap because
  the data does.

Learned interpolation then does what it is good at: smoothing the last few pixels between
rendered rig frames, backgrounds, cloth and hair, and the final 12→24 uplift if D-09 ever
permits one.

### 5.6 Cadence for the Studio path (owner decision D-09)

The qualification path stays at 12 unique fps with duplication (CR-004). For the Studio
and stage paths, which already author at 24 fps, propose to the owner that Pixar-style
output is rendered **on ones at 24 fps**, with the option of **mixed cadence** (holds and
slow moves on twos, fast actions and arcs on ones), which is the classic 2D compromise and
is what modern stylised features do. This is a proposal, not a change.

### 5.7 Stronger interpolator, same contract (needs admission; see section 6)

Where pixel interpolation remains in use, three drop-in improvements keep the current
adapter boundary:

* a newer Practical-RIFE v4.x checkpoint (v4.7–4.10 are described upstream as tuned for
  anime; v4.25/v4.26 are the latest), pinned with digests and an admission record, using the
  existing `PINNED_MODELS` mechanism (DEC-0011 explicitly allows this substitution);
* **recursive midpoint synthesis** for large gaps: generate t=0.5 from the anchors, then
  t=0.25 and 0.75 from anchor+midpoint, and so on, so each inference sees half the
  displacement. Cost is the same number of invocations; quality on large motion is usually
  better. Needs a measurement on the ramp check before adoption;
* `tta_spatial` (`-x`) is already supported and halves ghosting in some cases at 2–8×
  cost; measure before recommending.

---

## 6. Open-source references

Licence column: what was found on 2026-11-27 from the project page or model card.
Every entry needs the LICENSE file read and a DEC-0016 admission record before execution;
"verify" marks entries where the sources disagreed or the file was not visible.
CPU column is about *inference feasibility on the P-L envelope*, not qualification.

### 6.1 Frame interpolation (same job as the current adapter)

| Model | What it adds | Licence | CPU | Fit |
| --- | --- | --- | --- | --- |
| Practical-RIFE v4.7–4.10 / v4.25 / v4.26 (hzwer) | Same v4 architecture family as the pinned v4.6, arbitrary timestep, newer training; 4.7–4.10 described upstream as tuned for anime scenes | MIT (code and models stated upstream) | yes, same cost class | Direct substitution via `PINNED_MODELS`; ncnn conversions exist in the TNTwise fork (verify digests and provenance) |
| FILM (Google Research, ECCV 2022) | Designed for *large motion* between near-duplicate photos seconds apart; multi-scale feature pyramid, Gram-matrix style loss for disocclusions | Apache-2.0 reported; verify LICENSE | TF2, heavy but CPU-capable at 640×360 | Best classical-style candidate for 20–60 px pose gaps |
| AnimeInterp (CVPR 2021, ATD-12K) | First cartoon-specific interpolator: segment-guided matching for flat colour and large nonlinear motion | verify | yes (PyTorch, small) | Trained on the right domain |
| EISAI (ECCV 2022) | Perceptual-quality anime interpolation (line/flat-region aware losses) | verify | yes | Pair with AnimeInterp as the cartoon control |
| SGM-VFI (CVPR 2024) | Sparse global matching for large motion | verify | GPU-oriented | Reference only |
| AnimeInbet (ICCV 2023) | Geometrised line-art inbetweening | verify | yes | Only for line drawings, not coloured frames |

### 6.2 Generative inbetweening (different contract: GPU, prompt/sketch-steered)

| Model | What it adds | Licence | CPU | Fit |
| --- | --- | --- | --- | --- |
| ToonCrafter (2024) | Video-diffusion cartoon interpolation; handles disocclusion and large pose change; optional sketch guidance | Apache-2.0 on the HF model card, repo states research exploration, not commercial; verify | no (CUDA, tens of GB) | Separate "optional AI" profile per Studio handoff §4.1; cannot qualify CPU |
| ToonComposer (Tencent ARC, Aug 2025, ICLR 2026) | Sparse sketch keyframes at arbitrary timestamps → inbetweening + colourisation in one pass | MIT on HF card, "other" on GitHub; verify | no | Most production-shaped of the generative options |
| Wan 2.1 FLF2V-14B / Wan 2.2 | First-and-last-frame video generation, prompt-steerable motion | Apache-2.0 | no | Could generate the *breakdown* frames an artist would draw |
| LTX-2.x keyframe conditioning | First/last frame conditioning, fast | community licence, revenue-gated | no | Watch, do not adopt |

### 6.3 Rig, motion prior and retargeting (the "performance" layer)

| Tool / model | What it adds | Licence | CPU | Fit |
| --- | --- | --- | --- | --- |
| Animated Drawings (Meta) | Single drawing → mask, joints, ARAP mesh, 2D rig; BVH retargeting with frontal/sagittal projection; bundled motions | MIT (verify LICENSE) | yes | Closest existing solution to "flat generated character that moves with weight" |
| MDM (Human Motion Diffusion Model) | Text → 3D skeletal motion with natural arcs and weight | MIT code; datasets (HumanML3D/AMASS) research-only; SMPL licence | feasible, slow | Generate reusable action clips offline, store as BVH |
| MoMask | Faster text-to-motion; CPU demo runs | MIT code, same dataset caveats | yes | Same use as MDM |
| CMU Motion Capture Database | 2,500 free BVH/ASF clips: walks, runs, gestures | free for any use (verify attribution text) | n/a | Motion library without dataset restrictions |
| Blender Rigify + Grease Pencil 3 | Proper armatures (IK/FK, stretch-to, spline IK, bendy bones), NLA action blending, F-curve noise modifiers, GP interpolate/breakdowner for 2D | GPL tool; output unencumbered | yes (already used) | Replace the ad-hoc ellipsoid rig; GP gives real 2D line animation in the same process |
| Godot 4 (Bone2D, SkeletonModification2D) | Measured in S1; fastest of the two S1 backends | MIT | yes | Already a candidate |
| Synfig Studio | Vector cut-out animation with bones and a headless `synfig` CLI | GPL | yes | Lightweight 2D alternative to Godot |
| Inochi2D | Live2D-style puppet deformation (mesh warp, physics on hair/cloth) | BSD-2 | yes | For secondary motion on illustrated characters; headless path to verify |
| OpenToonz | Studio 2D pipeline (Ghibli lineage), plastic tool mesh deformation | BSD-3 | yes | Editor-centric; headless export limited |

### 6.4 Measurement

* SPARC and log-dimensionless jerk (Balasubramanian et al., 2015) for trajectory smoothness.
* FreeVideo's take checker (Apache-2.0), already evaluated in S1, for picture faults; it
  does not measure motion quality.

---

## 7. Suggested experiments (evidence before adoption)

1. **Easing A/B on the learned path.** Implement 5.1, render the DEC-0011 ramp clip with
   `linear`, `ease-in-out`, `cubic-bezier(0.2,0,0.1,1)` and `overshoot(0.08)`; record the
   velocity profile (3.1) and have two reviewers score motion on the Studio 1–5 rubric.
2. **Key-spacing sweep.** Same shot with a pose gap of 8, 16, 32, 64 px at 640×360 through
   RIFE v4.6, RIFE v4.2x and FILM; report ghost area (pixels that are neither anchor colour)
   per frame. This turns the 5.2 threshold from proposed to measured.
3. **Rig versus pixels.** One 3 s wave-and-turn shot rendered three ways: RIFE from two
   poses; RIFE from five poses with breakdowns; Animated Drawings rig driven by a CMU wave
   clip. Blind review at speed and frame-stepped.
4. **Life layer on/off.** The `workshop-reaction` example with and without 5.3, reviewed
   blind. This is the cheapest test of the largest claimed effect.

All four produce comparative evidence only; none is a §12.0 measurement.

---

## 8. Finding-to-action table

| Finding | Action | Section | Needs owner decision |
| --- | --- | --- | --- |
| F1 learned path linear only, rejects `timing` | shared timing module; RIFE honours eased `-s` | 5.1 | no (record boundary for qualification runs) |
| F2 one global curve | per-channel / per-part timing with stiffness filter | 5.1, 5.3 | no |
| F3 straight-line targets | Bezier arcs in `Blocking.resolve` | 5.3 | no |
| F4 no overlap/follow-through | second-order filter per body part | 5.3 | no |
| F5 dead holds | hold frames in the timing layer; breathing/blink/weight-shift layer | 5.1, 5.3 | no |
| F6 large pixel gaps | pre-flight displacement check; breakdown-drawing rule; rig path for acting | 5.2, 5.5 | S2–S4 scope |
| F7 instant finger curl | eased multi-frame curl | 5.3 | no |
| F8 no life layer | as F5 | 5.3 | no |
| F9 no smoothness metric | flow-based velocity/jerk/synchrony in take review | 5.4 | no |
| Cadence for Pixar look | 24 fps on ones / mixed cadence for Studio output | 5.6 | **D-09** |
| Newer interpolator | pin v4.2x or FILM with digests and admission | 5.7, 6.1 | **DEC-0016 admission** |
| Generative inbetweening | separate GPU profile, never qualification evidence | 6.2 | **owner: hardware, spend, rights** |

---

## Appendix A. Commands run for this review

Development container, Python 3.13.18, FFmpeg from `/usr/bin`, no RIFE runtime
installed, no Blender. Exploratory only.

```bash
python3 -m pip install -e .
python3 -m animalite fixtures generate --out-dir fixture
python3 -m animalite render --profile classical-warp-baseline \
    --anchors fixture/fixture-two-anchor/anchors.json --workspace ws --json
python3 -m animalite render --profile classical-warp-baseline --control timing=ease-in-out \
    --anchors fixture/fixture-two-anchor/anchors.json --workspace ws-ease --json
python3 -m animalite render --profile rife-ncnn-v4.6-cpu --purpose research \
    --control timing=ease-in-out \
    --anchors fixture/fixture-two-anchor/anchors.json --workspace ws-rife --json
ffmpeg -v error -i <output.mp4> -f rawvideo -pix_fmt rgb24 <name>.rgb
```

Observed: classical synthesis 8.13 s for 72 animation frames at 640×360 (single run);
delivery stream 144 frames at 24 fps; hold pairs differ only by codec noise (MAD ≈ 0.02
against ≈ 0.11 for a motion step). The velocity profile was computed as the mean absolute
RGB difference between consecutive animation frames (every second delivery frame),
averaged in ten equal bins.
