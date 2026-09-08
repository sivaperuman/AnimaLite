# CPU-stage requirements extract (from v0.12)

> **Status of this file.** This is a *checked extract* of the CPU-stage clauses
> of `Frame_Conditioned_2D_Video_System_Requirements_v0.12.docx`, produced for
> convenient review alongside the Package A code. It is **not** an authoritative
> replacement for the source document. It covers the CPU stage only, abridges
> some prose (marked *[abridged]*), and omits every clause outside this work
> package's scope. **Where this file and the .docx disagree, the .docx governs.**
> Digests of the source documents are in `README.md`.

> **Status of the targets themselves.** §12.0 opens by saying these are "proposed
> engineering acceptance targets for D-02 approval, not benchmark results", that
> "the current document contains no P-L measurements", and that approving the
> specification "authorizes a feasibility plan, not a claim that these speeds are
> attainable". Nothing in this repository changes that.

---

## §6.0 CPU quick-clip core

The core accepts **2–4 approved, time-indexed frames**, optional masks and
bounded motion controls. A compact learned temporal component estimates inbetween
frames or motion/visibility fields; CPU warping/compositing preserves source
detail and a CPU encoder packages the clip. Cache input features within a job,
stream frames and reuse unchanged assets, **but include every required stage in
timed execution**. A minimal CLI is sufficient for the first proof.

Evaluate a classical warp/flow baseline and one pinned RIFE/ncnn CPU candidate
first. If justified, test one smaller exported/quantized variant. Do not start
foundation-model training or a broad model survey by default. Deployment must not
require training or per-shot accelerator preparation. **Unsupported motion must
be reported honestly, not silently routed to cloud.**

The initial capability is constrained frame-conditioned 2D animation, **not**
general text-to-video. *[abridged]*

## §6.3 Normalized motion adapter contract

Every deterministic or generative adapter must expose the same lifecycle even
when an engine supports only a subset of controls:

| Operation | Returns |
| --- | --- |
| `validate(engine_profile, shot_manifest, resolved_assets)` | validation report |
| `estimate(job)` | device-class-agnostic `ResourceEstimate` |
| `submit(job)` | immutable job identifier |
| `status(job_id)` | queued / running / succeeded / failed / cancelled plus progress and diagnostics |
| `cancel(job_id)` | cancellation result |
| `collect(job_id)` | output media, preview, frame metadata and execution manifest |
| `capabilities(engine_profile)` | supported tiers, tasks, resolutions, frame ranges and controls |

`ResourceEstimate` must separate **reusable setup**, **incremental per-shot
setup** and **marginal render**. Reusable setup is an array of typed units with
`unit_kind`, `unit_count`, `artist_hours_per_unit` and
`accelerator_minutes_per_unit` plus integration overhead. Also expose
`preparation_active_seconds`, `preparation_wall_seconds`, `cold_start_seconds`,
`preview_wall_seconds`, `render_encode_wall_seconds`, `input_anchor_count`,
`animation_frame_count`, `delivery_frame_count`,
`peak_application_memory_bytes`, `thread_count` and `scratch_storage_mb`.
Preserve `estimated_cost`, existing setup fields and optional
`accelerator_type`/`memory`/`minutes`. P-L records the exact §12.0 execution
boundary and actual device trace.

## §6.4 Motion tiers (E3 row, and the routing rule)

| Tier | Engine class | Suitable motion | Required inputs | Compute |
| --- | --- | --- | --- | --- |
| E3 | Keyframe-conditioned interpolation | Inbetweening between approved nearby states on the same layer | Time-indexed keyframes, optional masks/flow controls and scene-cut boundaries; **§12.0 additionally limits the quick-clip path to 2–4 anchors** | CPU target; learned profile must prove P-L quick-clip and applicable P-E episode gates separately |

Routing rule: use the lowest tier that preserves the creative intent. A difficult
shot should first be split, shortened or supplied with additional keyframes
before E4 promotion. *[E0–E2 and E4 rows omitted — outside this work package.]*

---

## §12.0 CPU quick-clip acceptance contract

**Status and precedence.** These are *proposed* engineering acceptance targets
for D-02 approval, not benchmark results. Once locked, all Must conditions apply
together. They govern the low-spec model claim; §12.3 remains a separate 1080p
episode-production budget.

| Dimension | Proposed P-L acceptance target | Scope / priority |
| --- | --- | --- |
| Host | 4 physical CPU cores / up to 8 threads; 8 GiB RAM; SSD; no GPU/NPU inference or hardware encoding | Must; exact SKU, power policy, OS and runtime locked in D-02. Not a guarantee for every 4-core CPU. |
| Input / capability | 2–4 approved frames for a 6-second clip; bounded stylized-2D motion; learned temporal synthesis | Must; optional masks/controls must fit preparation limits. Dense inbetween input cannot count. |
| Core output | 640×360; 72 animation frames; 12 animation fps; 144 delivery frames at 24 fps | Must; two-frame holds form the delivery stream. Report synthesized, source and duplicate frame counts separately. |
| Warm preview | p95 ≤ 15 s to a playable 3-second 320×180 preview, 12 animation fps | Must; timing includes preview synthesis, normalization and CPU encode. A thumbnail or reused output is not a preview pass. |
| Warm final | p95 ≤ 60 s to the complete 6-second 360p clip | Must; real-time factor = wall time / output duration ≤ 10 at p95. Every warm run ≤ 90 s. |
| Process-cold final | p95 ≤ 90 s from launch to complete 360p clip; every run ≤ 120 s | Must; model load and initialization included. OS file cache may remain warm and must be reported. |
| Application memory | Peak ≤ 4 GiB across the app, temporal worker and encoder; no swap reliance | Must; measured process-group/cgroup peak with method disclosed on the 8 GiB host. |
| Per-shot preparation | ≤ 5 active user minutes and ≤ 30 s automatic local preprocessing | Must for the fresh-input test, after approved source frames exist; no required bespoke rig, dense drawing or accelerator stage. |
| Quality | All 12 locked in-scope clips pass identity and motion ≥ 8/10, no zero dimension, endpoints and no severity-2/3 defect | Must; two reviewers, frame stepping and normal playback. **No quality waiver for CPU qualification.** |
| 720p extension | 6 seconds at native 1280×720; warm p95 ≤ 120 s on the same P-L host | Should; separately benchmark and label. Upscaled 360p is not native-720p temporal inference. |

### Measurement boundary

For a **warm** run, begin at submission of a valid local job with approved inputs
already installed and end when the encoded file is closed and decodable. Include
input decode, all job-specific feature/mask/flow preparation, temporal inference,
warping, compositing, normalization, frame duplication and CPU encode. **Only
model/runtime residency may be reused**; no cached final frames, precomputed job
features or prior output may satisfy the primary warm target. Measure true
repeat-edit caching separately. Record preview and final as independent requests;
also report their combined time when the UI executes both.

For a **process-cold** run, restart the application/worker and start the timer
before initialization. **Do not label this disk-cold or installation time.**
Report model download/install, initial graph compilation, input artwork creation,
local preparation and review time separately. No network calls, GPU/NPU kernels
or accelerator encoding are allowed in the P-L test; runtime/device traces and an
offline rerun are required.

### Sample and pass calculation

Before timing, freeze **12 six-second in-scope clips**: four face/reaction, four
bounded hand/arm or body gesture and four cloth/hair or limited-overlap. Include
**at least two clips using only two anchors**; the others may use at most four.
Supply withheld artist-approved interior references for review, not as model
inputs. Lock intended action, source hashes, anchor indices, masks, settings and
quality rubric. **First/last anchors map to animation indices 0 and 71**; 72
animation frames duplicated to 144 delivery frames encode exactly six seconds.
Duplicated delivery fps is never reported as new temporal information.

Use a **separate development set for tuning**. For qualification, run each of the
12 clips **three times warm (36 runs) and once process-cold (12 runs)**, in a
fixed randomized order at **batch size one** with no competing workload. Report
all run times, peak memory, failures, timeouts, median and **nearest-rank p95
(sorted index `ceil(0.95 × n)`)**. All 12 clips must pass quality and every run
must return a valid output; **a timeout or invalid output fails the sample and
remains in the ledger**. Retuning requires a new profile revision and complete
rerun, **not deletion of weak cases**. Also run a continuous 20-minute workload
and report thermal/power throttling and whether latency or memory limits are
breached.

AT-056 additionally uses **four new input packs** without prebuilt rigs/layers to
measure active setup and local preprocessing. **Four locked out-of-scope cases**
— large viewpoint change, newly exposed unseen content, a scene cut and
conflicting anchor timing — must be rejected or explicitly routed to redesign
before synthesis. E0/E1 controls may be timed separately, but are excluded from
the 12 learned-motion cases and cannot pad the pass rate. **A rejected in-scope
clip is a failure, not a newly declared out-of-scope case.**

### Stop/go rule

Timebox the first feasibility spike to five working days after inputs, licences
and the exact P-L contract are ready. A failure triggers an evidence-backed
choice: optimize the bounded model, narrow capability with explicit owner
approval, revise the speed target as a new requirement, or stop the model path.
**Do not compensate by adding E0 footage, moving work to a GPU, supplying dense
manual frames or calling upscaled output native synthesis.** Passing establishes
only the stated constrained animation capability on the tested host. *[abridged]*

---

## Selected requirement rows

| ID | Requirement (abridged where marked) | Priority |
| --- | --- | --- |
| SM-19 | On the D-02-locked P-L host, AT-055 and AT-056 pass the complete §12.0 contract before broad Phase 1 benchmarking and again on the integrated MVP at Phase 2 exit. Targets are proposed until signed; **no measured pass exists in this document**. | Must |
| CR-004 | Animation cadence and delivery frame rate must be locked at project level. **Frame duplication is the default conversion** from 12 unique fps to 24 delivery fps; interpolated uplift requires an owner, reason, downstream impact and a separately measured compute budget. | Must |
| CR-006 | `estimate()` must return a device-class-agnostic `ResourceEstimate`; accelerator type and memory are **optional** fields, not required contract fields. | Must |
| CR-010 | E0–E3 profiles must be bit-repeatable inside a pinned execution profile that includes OS/container and binary hashes, CPU/SIMD policy, thread count/affinity, math-runtime settings and seeds where applicable. *[cross-host tolerance clause abridged — see §15.2]* | Must |
| CR-025 | The CPU-core profile must pass the complete §12.0 contract on the D-02-approved P-L host before broad Phase 1 benchmarking or MVP commitment, and pass again on the integrated Phase 2 build. **A P-E throughput pass, GPU result, dense manually supplied sequence or weakened target does not discharge this requirement.** | Must |
| MR-010 | Unsupported inputs, missing tier assets and exhausted budgets must fail validation **before expensive execution begins**. | Must |
| MR-013 | Profile must state peak system RAM, pinned thread configuration, reusable setup by unit class, incremental artist setup, setup wall time, marginal render time, expected attempts, repeat-render cost ratio, storage and separate setup/render accelerator memory/minutes where applicable. | Must |
| MR-015 | A local profile must not silently send project assets to an external service. | Must |
| MR-016 | Every profile must declare deterministic, ML-assisted or generative class; supported E0–E4 tiers; required assets; and whether CPU-only execution is guaranteed. | Must |
| MR-018 | The P-L model must synthesize temporally intermediate content from 2–4 approved frames on the locked in-scope motion sample. Its learned component must participate in temporal synthesis, not only segmentation or upscaling. **Camera transforms, cross-fades, repeated source frames, stock loops and pre-authored dense animation alone cannot satisfy this requirement.** Unsupported action must be rejected or sent for explicit redesign; no hidden accelerator fallback. | Must |
| NFR-002 | Interrupted jobs must retain diagnostic state and may be retried as new attempts. | Must |
| NFR-003 | All source and generated assets must be content-hashed; export packages must include checksums. | Must |
| NFR-013 | Jobs must emit structured logs, active artist/setup records, setup wall time, marginal render time, pinned CPU/thread settings, peak system memory, separate accelerator metrics, retries and failure category. | Must |
| NFR-015 | Output-affecting settings must be explicit, versioned and exportable. | Must |
| NFR-019 | Normalization must avoid interpolation, resampling or colour changes beyond the selected cadence and media policy. The project default for 12-to-24 fps is **frame duplication**. | Must |
| NFR-028 | The CPU-core benchmark and integrated MVP must retain the §12.0 cold/warm/preview timings, preparation effort, all-run quality/failure ledger, frame-count semantics, peak application memory and offline/device evidence. **No stage may be hidden as unreported setup or a silent accelerator/remote fallback.** | Must |
| C-05 | The pipeline must preserve original user assets and prior approved outputs across retries. | Constraint |

## Acceptance tests

| ID | Test | Expected result | Priority |
| --- | --- | --- | --- |
| AT-055 | Qualify fast sparse-frame CPU video | Run the locked §12.0 learned-motion sample on P-L. All outputs, quality/endpoint checks, memory/device evidence and complete warm/cold/preview latency distributions meet the same approved contract. **E0/E1 controls, duplicated frames, output caches and P-E/E4 results cannot substitute.** Repeat on the integrated Phase 2 path. | Must |
| AT-056 | Verify fresh-input effort, offline path and honest limits | Using the four fresh packs, meet §12.0 active preparation and automatic preprocessing limits without bespoke rigs, dense inbetweens or accelerator preparation. Run offline after installation and prove CPU-only inference/encode. Four locked unsupported cases reject or request explicit redesign; **no hidden cloud/GPU fallback.** Record source-artwork and install/compile effort separately. Repeat on the integrated MVP. | Must |

Both are first due at **Phase 1**, mode **Local P-L; mandatory CPU-core gate**.
AT-055 covers SM-19, CR-025, MR-013, MR-017, MR-018, NFR-028. AT-056 covers
SM-19, CR-025, MR-015, MR-017, MR-018, NFR-028.

## §13 P-L deployment profile

| Profile | Planning envelope | Likely use | Decision rule |
| --- | --- | --- | --- |
| P-L — Low-spec CPU core | 4 physical cores / up to 8 threads; 8 GiB RAM; SSD; CPU-only inference and encoding; exact SKU/power/runtime pinned | Mandatory §12.0 sparse-frame quick clips | AT-055/AT-056 must pass here before broad benchmark/MVP commitment; iGPU/NPU use is a separate profile |

## Appendix E.1 — the discharge rule that keeps this package open

> A coverage link may be discharged only at or after the covered requirement
> clause's release gate. An early test run discharges only clauses already due;
> later clauses remain open/carry-forward. [...] **Unchanged input fingerprints
> alone are not proof that an earlier harness exercised a later implementation.**

And from the gate-rule regression fixtures:

| Early evidence | Must remain open | Later discharge condition |
| --- | --- | --- |
| AT-055/AT-056 pass CPU feasibility | CR-025 integrated MVP clause | Phase 2 delivered path repeats P-L quality, preparation, latency, memory and offline checks. |

This is why `docs/verification/package-a-traceability.md` records **no**
discharged Must clause for Package A: a harness that has not run a learned model
on an approved host has not produced a witness for any of them.

## Open owner decisions referenced by this package

| ID | Decision | Gate |
| --- | --- | --- |
| D-02 | Approve the exact P-L CPU SKU, sustained power/thermal policy, OS, RAM and CPU-only runtime **plus §12.0 quality, sparse-input, latency, preparation and memory thresholds before its timed runs**. Core count alone is not hardware equivalence. Any later relaxation creates a new target revision and reruns the affected sample; it is not a pass against the former goal. | Phase 0 Days 4–5 |
| D-06 | Licence policy: permissive-only production, or allow custom community licences. | Before model shortlist lock |
| D-09 | Cadence policy: approve or replace the 12 unique fps → 24 fps duplication convention. | Phase 0 Week 1 |
