# DEC-0012 — RIFE invocation strategy and the model-load cost

* **Status:** Accepted, with a measured case for a follow-up optimisation
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

`-n` performs recursive 2x doubling (2 → 3 → 5 → 9 → 17 → 33 → 65) and pads to
the requested count. The motion completes by roughly frame 37 and then holds on
the end anchor. **Maximum deviation from a uniform ramp: 20.15 px.**

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
a P-L result**:

| Approach | Per frame | 70 frames | Frame indexing |
| --- | --- | --- | --- |
| Per-frame `-s` (implemented) | 0.457 s | **32.0 s** | correct (2.60 px) |
| Directory mode `-n` | ~0.19 s | 7.2 s | **broken (20.15 px)** |

So roughly **19 s of the 32 s is re-loading the model 70 times**. Handoff §5 is
explicit: *"If a candidate CLI loads weights for every invocation, count that
cost."* It is counted — the whole loop runs inside the `temporal_synthesis`
stage, inside the §12.0 warm boundary — and the adapter records
`invocations=` and per-frame subprocess wall time as attempt-log notes, so the
overhead is visible rather than inferred.

A full 72-frame render measured **35.85 s end to end** (synthesis 35.34 s,
encode 0.25 s, decode/validate/publish the rest).

## The follow-up, deliberately not built yet

Handoff §2 permits *"a small persistent native worker … to keep the model
resident"*. The measurement above is the case for one: it would recover most of
the ~19 s. It is **not** built yet because:

* the target host does not exist — D-02 has not approved a P-L machine, so
  there is nothing to optimise against, and this container is not it;
* 35.85 s already fits the proposed 60 s warm p95 **here**, so the worker is not
  yet demonstrably necessary;
* a persistent worker means either a C++ component built against ncnn or
  reimplementing the wrapper's pre/post-processing, both of which add
  substantially more risk than the current subprocess boundary.

The trigger for building it is a measured warm p95 on the D-02-approved host
that does not clear the target with margin. Recorded so that decision is made
against evidence rather than taken now on a guess.

## A related bug this surfaced

Instrumenting the stages showed that the adapter's time was being attributed to
the **encoder**: `synthesize()` is a generator consumed lazily by the encoder
writer, so the stage timer around its construction measured ~0 s and all 35 s
landed in `encode`. Total wall time was correct, the breakdown was not. Since
NFR-028 forbids a stage being hidden or misreported, the service now measures
the time spent inside the adapter generator and subtracts it from the encode
stage. This affected the fixture adapter equally; it was simply too fast to
notice.
