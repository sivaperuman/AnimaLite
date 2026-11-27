# DEC-0012 — RIFE invocation strategy and the model-load cost

* **Status:** Accepted. Two explanations corrected and one cost estimate
  withdrawn after PR-2 review (B-R7); the invocation decision is unchanged
* **Deciding role:** implementation
* **Affects:** §12.0 measurement boundary and frame semantics, CR-004, NFR-028,
  handoff §2 (model integration) and §5 (counting load cost)

## Decision

Synthesize **one subprocess per frame, with an explicit `-s` timestep**. Do not
use the upstream tool's directory mode, despite it being roughly 2.4x cheaper.

## Why not the cheap path

`rife-ncnn-vulkan` has a directory mode (`-i indir -o outdir -n count`) that
loads the model once. Asking it for 72 frames from two anchors:

| frame | 0 | 10 | 20 | 30 | 40 | 50 | 60 | 71 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| subject x | 138.9 | 150.5 | 161.0 | 173.9 | **179.8** | **179.8** | **179.8** | **179.8** |

### Correction: the mechanism is index arithmetic, not recursive doubling

An earlier version of this record said `-n` performs recursive 2x doubling
(2 → 3 → 5 → 9 → 17 → 33 → 65) and pads. It does not. The pinned wrapper's
[directory indexing](https://github.com/nihui/rife-ncnn-vulkan/blob/a7532fc3f9f8f008cd6eecd6f2ffe2a9698e0cf7/src/main.cpp#L713)
maps output *i* onto the input list by a scale factor, with the final pair
clamped:

```c
double scale = (double)count / numframe;
float fx = i * scale;
int sx = static_cast<int>(floor(fx));
fx -= sx;
if (sx >= count - 1) { sx = count - 2; fx = 1.f; }
```

With `count = 2` input files and `numframe = 72`, `scale = 1/36`. For *i* < 36,
`sx = 0` and the timestep is `i/36`: the motion completes over the first 36
outputs. From *i* = 36 the clamp fires — `sx = 0`, `fx = 1.0` — so every
remaining output is requested at timestep exactly 1.0, which is the end anchor.

That is the measured behaviour precisely: the ramp finishes around frame 36–37
and then holds. **Maximum deviation from a uniform ramp: 20.15 px.** The
observation was right; the explanation of it was not.

That would silently violate the §12.0 frame-index contract — frame *k* would not
be at temporal position *k* — and it would corrupt the source / synthesized /
duplicated accounting, because the padded tail frames are duplicates being
reported as synthesized. Every downstream check would still pass.

With explicit per-frame timesteps the same clip measures **2.60 px** maximum
deviation, and every frame retains a solid subject (≥ 9 865 pure-colour pixels,
against ~5 400 for a cross-fade).

Correct frame semantics are not negotiable against a speed saving, so the
expensive path is the one implemented.

## The cost, measured and counted

On the development container (4 cores, 640×360, `-j 1:2:1`) — **exploratory, not
a P-L result**, single runs, no repetition:

| Approach | Per frame | 70 frames | Frame indexing |
| --- | --- | --- | --- |
| Per-frame `-s` (implemented) | 0.457 s | **32.0 s** | correct (2.60 px) |
| Directory mode `-n` | ~0.19 s | 7.2 s | **broken (20.15 px)** |

A full 72-frame render measured **35.85 s end to end** (synthesis 35.34 s,
encode 0.25 s, decode/validate/publish the rest).

**What this difference does not establish.** An earlier version of this record
said "roughly 19 s of the 32 s is re-loading the model 70 times". That figure
is withdrawn: the two rows are not the same work, so their difference does not
isolate the reload cost.

* The directory run produced *different frames*. From output 36 onwards it asked
  for timestep 1.0 (see the correction above), which is not the same computation
  as an interior timestep.
* The directory run also pipelines. On the CPU path the wrapper runs the load,
  proc and save stages as concurrent threads, so image I/O for one output
  overlaps inference for another; the per-frame path serialises them.
* Both rows are single runs on a container that is explicitly not the target
  host, with no repetition and therefore no variance estimate.

What *is* established, and is what handoff §5 asks for: the per-frame path loads
the model once per synthesized frame, and that cost is **counted**. The whole
loop runs inside the `temporal_synthesis` stage, inside the §12.0 warm boundary,
and the adapter records `invocations=`, the thread allocation and per-frame
subprocess wall time as attempt-log notes, so the overhead is visible rather
than inferred. Isolating the reload component needs a comparable sample —
same timesteps, same concurrency, repeated — which is a measurement on the
D-02-approved host, not a rearrangement of these two numbers.

## The follow-up, deliberately not built yet

Handoff §2 permits *"a small persistent native worker … to keep the model
resident"*. It is **not** built yet, and the case for it is currently *plausible
rather than measured*:

* per-frame invocation does reload the model 70 times, and that is real work
  a resident worker would not repeat — but how much of the 32 s it accounts for
  has not been measured (see the withdrawal above);
* the target host does not exist — D-02 has not approved a P-L machine, so there
  is nothing to optimise against, and this container is not it;
* one 35.85 s run on this container is not evidence about a p95 anywhere. A
  single observation has no percentile, and the earlier "already fits the
  proposed 60 s warm p95 here" claim is withdrawn on that ground alone;
* a persistent worker means either a C++ component built against ncnn or
  reimplementing the wrapper's pre/post-processing, both of which add
  substantially more risk than the current subprocess boundary.

The trigger for building it is a measured warm p95 on the D-02-approved host
that does not clear the target with margin, together with a comparable
measurement of what a resident model would actually save. Recorded so that
decision is made against evidence rather than taken now on a guess.

## A related bug this surfaced

Instrumenting the stages showed that the adapter's time was being attributed to
the **encoder**: `synthesize()` is a generator consumed lazily by the encoder
writer, so the stage timer around its construction measured ~0 s and all 35 s
landed in `encode`. Total wall time was correct, the breakdown was not. Since
NFR-028 forbids a stage being hidden or misreported, the service now measures
the time spent inside the adapter generator and subtracts it from the encode
stage. This affected the fixture adapter equally; it was simply too fast to
notice.
