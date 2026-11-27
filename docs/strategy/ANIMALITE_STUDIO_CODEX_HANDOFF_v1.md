# AnimaLite Studio — Architecture, Technical Roadmap and Business Case

**Version:** 1.0 (proposal for Codex implementation planning)  
**Prepared:** 2026-11-19  
**Repository:** https://github.com/sivaperuman/AnimaLite  
**Audience:** Repository owner, Codex implementation agent, architecture/quality reviewers  
**Scope:** New creator-oriented animation-production capability alongside (not instead of) AnimaLite v0.12  
**Decision status:** PROPOSED — nothing in this document authorizes changes to the existing signed requirements, legal decisions, runtime admissions, benchmark results or protected branch policies.  
**Related tracking issue:** https://github.com/sivaperuman/AnimaLite/issues/3

> **Starting instruction for Codex:** This file is a technical/business-case handoff, not a request to implement everything in one task. First check the live repository and open PRs, read source requirements and AGENTS.md on the appropriate branch, complete the Stage S0/S1 feasibility work, and submit a small reviewable PR with evidence. Do not merge or change owner-only decisions. Preserve project behavior and exact evidence boundaries.

---

## 1. Executive decision and purpose

**Recommendation:** Build a distinct, locally runnable **AnimaLite Studio** workflow for production of original 2D/2.5D stickman cartoons. Reuse AnimaLite's existing execution and media foundation while acquiring or integrating a real 2D character-rig, pose, animation and scene-rendering capability. **Do not attempt to fix poor character movement with frame interpolation alone.**

The creator currently makes short Milo stories, wants better physical movement, and intends to move toward globally understandable **10-minute YouTube comedy episodes** featuring **Milo** and his friend/rival **Max** (renamed from Balu). Current manual motion-comic animation has recognizable backgrounds but suffers from sliding limbs, weak foot plants, poorly timed reactions, and incomplete hand–prop contact. It is a product-quality problem, not a resolution problem.

**Decision principles**
1. Separate **authored performance animation** from **learned sparse-anchor temporal synthesis**; both can coexist, but one cannot be used as evidence for the other.
2. Start with a **12-second “Marvel Engineer” acting test**, not a broad editor or a 10-minute rendering job.
3. Prefer reusable character rigs, motion libraries, reusable locations and deterministic project files over paid image-to-video for every scene.
4. Retain an optional AI-assisted path only where needed, with explicit consent, per-attempt costs, content rights, and deterministic/manual alternatives.
5. Use the repository's established Pydantic/versioning, one execution path, bounded streaming, immutable attempts and truthful provenance.
6. Target global audiences: primarily visual, simple English if any, original characters, expressions readable without captions or dialogue.
7. Prioritize a **creator-first local tool**; do not build SaaS subscriptions, user accounts, marketplace or cloud fleet until creator workflow is proven.

**Non-goals of the first implementation:** General text-to-video generation; training a foundation model; automatic professional acting from a single flat image; making a full editor before proving rigged movement; replacing v0.12; proving the §12.0 CPU model qualification with dense authored frames; promising automatic comedy quality.

---

## 2. Verified repository baseline and authoritative sources

**Repository observation on 2026-11-19 (re-check before writing code):**
- Default branch **main** is not the source of the currently reviewed Python implementation.
- PR #1: https://github.com/sivaperuman/AnimaLite/pull/1 — open, technically reviewed **Package A**, branch **claude/animalite-package-a-tru8eq**, head observed **1a0be99d929c73356224f84076b23840b60526ec**. Implements Python package/CLI, versioned contracts, local job lifecycle, CPU decode/encode/validation, deterministic fixture, host/benchmark, logs and bounded cleanup. Approval does **not** mean all v0.12 Must requirements are discharged.
- PR #1 owner-only blockers: actual NOTICE copyright-holder and acceptance (or revision) of proposed DEC-0001 / PolyForm Noncommercial licensing. Do not invent the owner's identity or accept the license for them. The PR also notes pending doc-link corrections (N1).
- PR #2: https://github.com/sivaperuman/AnimaLite/pull/2 — open **draft**, stacked on PR #1; branch **claude/animalite-package-b-rife**, head observed **ab159d048a63ad02f711968b8643d9bf3c5c2de8**. Adds classical warp/flow and a pinned RIFE/ncnn CPU candidate. The learned candidate is not allowed to execute absent an artifact- and purpose-bound approval record. Qualification remains NOT_ELIGIBLE and AT-055/AT-056 have not passed.
- Issue #3: https://github.com/sivaperuman/AnimaLite/issues/3 — initial Studio RFC / motion test.
- Existing contracts in Package A: src/animalite/contracts/{shot,assets,media,profile,job,results}.py; adapter boundary in src/animalite/adapters/base.py; lifecycle in src/animalite/core/service.py; streaming media in src/animalite/media/.
- Existing example **640×360**, **72 animation frames at 12 fps** duplicated into **144 delivery frames at 24 fps**, **6 seconds** is **Package A's CPU sparse-anchor target**, not a universal frame-rate rule for authored character animation.

**Sources and precedence**
1. Authoritative: docs/requirements/Frame_Conditioned_2D_Video_System_Requirements_v0.12.docx in the implementation branch (where available), and any *owner-approved* subsequent revisions.
2. Implementation handoff: docs/requirements/AnimaLite_Implementation_Handoff_v0.2.md.
3. Human-readable checked subset: docs/requirements/cpu-stage-extract.md. It explicitly **does not replace the DOCX** and covers only the CPU stage.
4. Repo policies: AGENTS.md, CLAUDE.md, durable decisions and verified commands on the implementation branches.
5. This document: a **proposed additional Studio product scope**, not a change of authority.

**Rules from existing specification that must survive unchanged**
- §6.0: sparse approved anchors, learned temporal participation, explicit capability limits, CPU baseline.
- §6.3: validate / estimate / submit / status / cancel / collect / capabilities and truthful resource estimates.
- §6.4: E3 interpolation distinct from other motion tiers; route with explicit reasons.
- §12.0 and AT-055/056: locked host, sample, preparation, quality, memory, latency, offline/no hidden GPU/cloud, full evidence; proposed targets are **not measured passes**.
- CR-004/NFR-019: default 12→24 delivery conversion for the existing CPU profile is **frame duplication**, not newly synthesized motion; an uplift needs separate approval.
- MR-018: authored dense animation, crossfades, camera transforms, source-frame repeats and stock loops **cannot** qualify the learned component.
- NFR-002/003/013/015: retained failures and retries, content hashes, resource/provenance logs, versioned settings.

Studio must introduce **new profile semantics and its own acceptance rubric**, explicitly separate from the qualification ledger. It must not change a failing/NOT_ELIGIBLE v0.12 claim to “passed.”

---

## 3. Business case and product changes

### 3.1 Original positioning vs proposed added value

| Dimension | Existing AnimaLite scope | Proposed AnimaLite Studio capability |
|---|---|---|
| Primary job | Short useful motion from 2–4 approved stills on low-spec CPU | Build recurring-character comedy scenes and whole episodes with controlled acting |
| Primary user | Creator/operator with approved anchors, seeking cheap inbetweening | YouTube creator/director who needs reusable rigs, expressions, props and shot timing |
| Input | Approved indexed frames, optional masks/controls | Script/shot plan, editable character rigs, location/prop assets, action keyframes, audio cues |
| Result | Validated short MP4 and evidence of synthesis | Shot/scene/episode MP4, editable animation project, audit of assets/animation effort |
| Core differentiation | Constrained offline CPU temporal synthesis and evidence | Expressive consistent characters and repeatable, low-recurring-credit animation production |
| Quality question | Learned inbetween quality under the locked §12.0 contract | Motion/acting/prop continuity, comedic timing and finished-video usefulness |
| Monetization | Depends on separately approved legal/business position | Initially enable owner's content production; optional software business is a later decision |

**Primary business model for now:** creator productivity and differentiated content quality, not selling software subscriptions. A future marketplace / third-party deployment requires separate validation, legal review, support/security roadmap, packaging, billing and customer research.

### 3.2 Creator-oriented product requirements

**Must (first usable release)**
- One source-of-truth character rig each for Milo and Max; expressive face states, consistent proportions/outfits and color.
- Repeatable action clips: idle, walk/run with foot contact, look/turn, point, bend, reach/grab/release, surprised, proud, angry, facepalm.
- Reusable location backgrounds (house/building site first), layers, parallax, props and camera.
- Shot timeline with deterministic frame timing and editable action events; control of pauses, anticipation, punchline beats and physical constraints.
- Preview of a scene and an exported decodable MP4 with matching motion, audio cues and exact frame count.
- Scene-level retries and caching without rerendering unaffected shots; preserve revisions.
- Local/offline first by default and no implicit subscription/cloud expenditure.

**Should (following pilot)**
- Simple editor or preview tooling, layered artwork import, action-template library, pose inspector, time-coded dialogue/SFX, subtitles, aspect-ratio recomposition.
- 16:9 10-minute episode assembly and 9:16 Short variants, 1080p output when evidence supports it.
- Quick automatic QA for media format, asset refs, invalid motion ranges, transparency/edge artifacts, audio peaks, cut continuity.

**Later/optional**
- AI motion suggestion, reference-video motion capture, voice/lip-sync beyond basic expressions, richer physics, human review UI, multi-user asset library, GPU/remote render profiles.
- Monetizable SaaS only after actual production-quality and cost evidence.

### 3.3 Business KPIs (proposed, not observed)
Measure:
- Artist/creator **active hours per approved finished minute**.
- Cost per **approved** finished minute, including failed generations, render time, asset work, edits, subscriptions and amortized rig development.
- Character reuse: number of new shots/episodes without re-rigging.
- First-pass scene acceptance, total attempts, quality defects per 30 seconds, time to repair a shot.
- Animation review scores: motion naturalness, visual clarity, prop/eye contact, joke clarity, pacing.
- Actual export speed, machine utilization, peak memory and storage.
- Downstream YouTube retention, watch time, replay moments, click-through rate — **channel KPIs only**, not proof the software met animation requirements.

Do **not** invent an ROI figure, subscriber lift, guaranteed 10-minute production time, or a date by which the platform will be finished.

### 3.4 Economics model

**Cost per approved minute** =
(amortized software build + reusable asset/rig prep + scene-specific acting/keyframing + sound/editing + local compute + optional AI generations + failed attempts + review) / approved finished minutes.

Illustrative quantities (not a vendor quotation):
- 60 s at 24 fps = **1,440 delivery frames**.
- 10 minutes at 24 fps = **14,400 delivery frames**.
- If paid image-to-video was used for every second, a nominal 5 credits/s would mean 3,000 credits for 10 minutes once, or 6,000 with two attempts. This is illustrative, **not** a statement of current pricing or feature entitlement.
- If AI motion is restricted to 60 s of a 10-minute episode, the same illustrative cost is 300 credits once, or 600 with two attempts.
- Local rigging avoids **per-second third-party AI-video credits** for that deterministic footage but does not make artist time, CPU/GPU electricity, editor integration, support or maintenance free.

**Suggested cost evaluation:** compare (A) all AI-video, (B) all manually/keyframe-rigged, (C) hybrid. At equal accepted quality, compare *actual* person-hours + out-of-pocket cost for the same 12-second, 60-second and 10-minute workloads. Reassess once the rigging spike provides measured evidence.

**Initial engineering estimate — planning range, not commitment:** approximately **25–70 engineering days** for a bounded creator MVP, plus character-art/animation-authoring work. This range assumes a suitable renderer/rig solution can be integrated. An unsuitable framework, missing asset layers or commercial-rights issues can increase scope substantially. Require Codex to replace this range with task-based estimates after the first spike.

---

## 4. Proposed architecture and ownership boundaries

~~~text
Story / dialogue / timed shot plan
           |
           v
Studio Project + Episode/Shot Timeline (new, versioned, validated)
       |                    |
       v                    v
Character/rig library   Sets / props / camera / audio cues
       |                    |
       +-------> Pose + motion scheduler (actions, curves, constraints)
                                |
                                v
                   Rig Runtime / Scene Renderer
                   (selected only after S1 spike)
                                |
                       decoded RGBA/RGB frames
                                |
                                v
               AnimaLite Studio export adapter (new)
                                |
              existing bounded job/media/FFmpeg foundation
                                |
       media probe, exact frame counts, hashes, metadata, SFX mix
                                |
              immutable approved shot MP4 + manifests
                                |
               episode assembler -> full MP4 + QA
~~~

**Hard boundaries**
- New Studio animation and episode domain belongs in a separate module/namespace such as src/animalite/studio/, or a clearly justified integration package, **not hidden inside the sparse-anchor adapter contracts**.
- Existing core/contract layers must not import native rig libraries directly. Runtime integrations belong behind renderer adapters, with explicit capabilities and validated profiles.
- No silent remote calls, accelerator selection or model download; show intended execution mode **local CPU**, **local GPU** (if required for Studio), or **remote** separately. The §12.0 P-L proof remains CPU-only.
- Source artwork, references, character rigs and approved renders remain distinct, content-addressed assets.
- All output affecting decisions are versioned and included in the shot/episode manifest hash.
- For every run, distinguish **author-authored poses**, **procedural rig frames**, **AI/learned synthesized frames**, and **delivery duplicates**; never present keyframed animation as an E3 learned-model pass.
- Studio must reuse validation, status/cancellation, cleanup, per-attempt diagnostics and media verification patterns from Package A without compromising their guarantees.

### 4.1 Two compatible but separate engine paths

| Path | Produces | Frame-rate policy | Qualification |
|---|---|---|---|
| Existing E3 sparse-anchor CPU profile | Learned interpolation candidate from 2–4 anchors | Locked 12 unique/24 delivered with duplicate policy unless separately approved | AT-055/056 remain required and NOT_ELIGIBLE pending evidence |
| New Studio authored-rig profile | Intentionally posed animation generated at 24 fps (or declared production cadence) | Native authored frame count, no fabricated duplicates | New Studio quality/reliability rubric; **not** AT-055/056 |
| Optional AI scene generation | Explicitly labeled third-party-generated footage | Model output + declared normalization | Separate credits, provenance/rights and human approval |

The Studio path must never be used to bypass or “satisfy” the existing sparse-frame CPU requirements. If governance elects to discontinue the original learned proof, record that as an **owner-approved product/requirement pivot**, not an accidental code refactor.

---

## 5. Select a rig/renderer by evidence, not by assumption

A thin 2D rig can be written with hierarchical transforms and two-bone IK, but creating *professional* cartoon acting, mesh deformation, rigs, editing tools, facial performance, motion curves and video export is a much larger undertaking. Prefer an existing mature toolkit if it meets integration and license needs.

**Candidates to investigate, not approved dependencies:**

| Candidate | Why investigate | Critical due diligence |
|---|---|---|
| OpenBone — https://github.com/UXCentury/open-bone | Advertises 2D bones, IK, timeline, audio, exports, agent-editable MCP tools, permissive license | Verify real CLI/headless deterministic export, video/audio fidelity, resource use, maintenance, exact pinned artifacts/licenses and ability to ingest our separated artwork |
| Rigby2D — https://github.com/jaisurya-dev-art/rigby2d | Advertises layered SVG/PSD, rigging/IK, timeline, scene/video export and automation | Verify build reliability, exported project format, headless performance, actor/prop interaction, model/asset licenses and stable integration |
| Godot 4.x — https://godotengine.org/ | Established 2D skeleton/timeline and documented command-line Movie Maker mode | Measure actual reproducibility, required display/GPU renderer, audio export/capture, startup/caching, integration overhead, license notices |
| Small native AnimaLite rig adapter | Full control, local deterministic dependencies, minimal character design | High acting/art-quality risk; must implement/maintain IK, interpolation, rig authoring, silhouettes, motion-editor tooling |

**Spike evaluation matrix (record tested version, commit, environment, proof video and raw measurements):**
1. Can load and render **real editable layers** (not merely pan a flat AI image).
2. Can maintain planted feet during walks, credible weight shifts, head/gaze, two-hand blueprint hold, grab/release and fold.
3. Can export exact frame-indexed reproducible shots as PNG sequence or bounded frame stream, then valid H.264 MP4.
4. Supports local scripted/headless operation suitable for Codex without manually clicking a GUI.
5. Supports transparency, stage layers, 16:9/9:16 and reusable characters.
6. Can run acceptably on available host; measure CPU, GPU use, memory, disk and wall time. No inference about the locked P-L CPU qualification host.
7. Includes admissible licenses/third-party notices, and avoids dependency on proprietary sample character art.
8. Is maintainable: pinned releases, project schema/versioning, debugging/repair, surviving upstream changes.

**Selection gate:** require a visible side-by-side 5–12-second acting demo from **at least two feasible approaches** if practical. A comparison that is blocked by installation, rights or hardware must say “not tested,” not silently declare a winner. Do not develop a custom full rig editor before this decision.

---

## 6. Authoring model, typed contracts and assets

**Propose new versioned contracts**, using Pydantic v2, strict unknown-field rejection, content hashes, explicit units and integer frame indices. Contract names are **proposals**, not existing APIs:

- StudioProject: schema version, assets, actors, scenes, frame rate, default resolution, creative constraints, rights and render profiles.
- CharacterDefinition/RigDefinition: identity, bone hierarchy, pose geometry, skins, pivot/joint origins, expressions, compatible actions, asset hashes.
- StageDefinition: background/foreground layers, depth/parallax, lighting/color parameters, safe camera bounds, prop anchors.
- Episode / Scene / ShotTimeline: integer-frame begin/end, ordered events, shot cuts, camera keyframes, acting instructions, approval state.
- ActorTrack: rig reference, transforms and action clips, blending/easing, gaze targets, foot-lock intervals, expressions, hand/prop attachment state.
- PropDefinition: stage position and parent attachment, state transitions, visibility and allowed owner.
- AudioCue: SFX/dialogue/music file hash, license, trim/start frame, envelope, stereo, peak policies; optional subtitles and language.
- StudioRenderRequest / StudioOutputManifest: explicit renderer/model identity, device policy, timeline and asset hashes, generated-frame provenance, render/encode timing, resource use, diagnostics, attempts and output checksums.
- ReviewResult: human reviewer scores, defects and approval status; machine QA results stored separately.

**Suggested source asset layout**

~~~text
projects/milo-max/
  project.json
  characters/milo/{rig,poses,expressions}/
  characters/max/{rig,poses,expressions}/
  locations/construction-site/{background,foreground,props}/
  episodes/marvel-engineer/
    episode.json
    scenes/
    sound/
    reviews/
  manifests/       (small approved manifests + content hashes)
  exports/         (generated/ignored, with approved release metadata)
~~~

File and directory names above are illustrative; use the repository's actual project-storage strategy when it exists. **Do not commit heavy generated video/weights/artwork to Git**; keep immutable asset IDs and small provenances, and use a documented local/LFS/object-store arrangement as appropriate.

**Example of proposed episode/shot data, not executable current AnimaLite syntax:**

~~~yaml
schema_version: 1
project_id: milo-max
episode_id: marvel-engineer-pilot
output:
  width: 1280
  height: 720
  fps: 24
  aspect: "16:9"
  media: h264_mp4
shots:
  - id: building-reveal
    duration_frames: 72
    stage_id: construction-site
    camera: {move: tilt_up, target: upper_floor}
    actors:
      - {id: owner, action: look_up, expression: disbelief}
  - id: blueprint-unfold
    duration_frames: 120
    stage_id: construction-site
    props: [folded-blueprint]
    actions:
      - {actor: milo, kind: hold_prop, prop: folded-blueprint, hand: right, at_frame: 0}
      - {actor: owner, kind: transfer_prop, prop: folded-blueprint, at_frame: 24}
      - {actor: owner, kind: unfold_prop, prop: folded-blueprint, at_frame: 60}
  - id: angry-and-proud
    duration_frames: 96
    stage_id: construction-site
    actions:
      - {actor: owner, kind: angry_react, at_frame: 0}
      - {actor: milo, kind: proud_pose, at_frame: 36}
~~~

Total **72 + 120 + 96 = 288 frames = 12 seconds at 24 fps**. The schema still needs design decisions for events, camera easing, interpolation of positions, handoff constraints, exclusive prop ownership, shot-boundary continuity and audio alignment.

**State validity rules**
- Joint transforms must be finite, and pivots/layer IDs must resolve.
- Actor size, orientation, depth and eye direction must be consistent across a scene.
- One physical prop has at most one attachment owner at each frame; transitions require a handoff event with continuous position.
- Contact foot should not drift during locked intervals; scene/action conflicts must be rejected or require explicitly defined priority.
- A cross-fold disappearing from the blueprint must be a **visible animated prop transformation**, not a jump cut to an unrelated design image.
- Creative timing uses integer frames with exact duration, even when the source shot plan is in seconds.

---

## 7. Movement quality: first-class product requirement

The failed Marvel Engineer prototype demonstrates that animation quality is not obtained by moving a flat image on a spline. Every accepted reusable actor must provide:

- **Rig anatomy:** intentional head, torso, upper/lower arms, hands, upper/lower legs and feet; appropriate 2.5D layer ordering.
- **Locomotion:** stride phase, planted feet, stable root translation, turn/pivot, startup and stop, body weight, anticipation/follow-through.
- **Acting:** face library (curious, pleased, confused, horrified, annoyed, proud), eyebrow/eye/gaze direction, head turns, readable poses and holds for jokes.
- **Object interaction:** two-hand hold, reaching, gripping, prop ownership, blueprint opening, release and recovery; no floating prop.
- **Timing:** anticipation -> action -> reaction -> pause -> payoff; configurable keyframe curves with comic exaggeration.
- **Staging:** characters separated visually; no surprise jumps in actor scale, position, face/helmet, depth or camera.
- **Controllability:** artist/agent can inspect and change any action at an exact frame rather than rerendering an entire episode.

Audio/dialogue can remain minimal for global reach. Use original/correctly licensed music and SFX, with appropriate peak/ducking and an optional simple English vocal track.

A generic “more realistic motion” prompt is not a substitute for defining and testing these mechanics.

---

## 8. Execution / export / resource architecture

**Shot pipeline:**
1. Resolve and validate manifest and all content hashes.
2. Determine renderer profile (Studio-authored local, approved model, or explicit external service) and required device.
3. Calculate explicit setup, marginal render and optional billed external credits (a heuristic must say “estimated”).
4. Compile/check scene constraints and stage/rig/action asset availability before expensive rendering.
5. Render bounded frame chunks or a streaming frame iterator; annotate frame content provenance.
6. Composite stage layers, actors, props, camera and overlay-safe elements; handle alpha intentionally.
7. Mix dialogue/music/SFX with exact timestamps via a bounded media pipeline.
8. Encode video via externally installed FFmpeg (pin recorded build/license), validate by decoding/probing, check frame count, duration, resolution, audio and color metadata.
9. Publish atomically to an immutable attempt directory; retain logs, source/revision hashes, settings, timing, memory, faults and retry links.
10. On approval, promote a reference to the approved asset/shot; never destroy prior approved output on retry.

**Episode pipeline:** ordered approved shots -> cache unchanged shot hashes -> transitions, music/caption mix -> full episode encode -> decode QA -> release manifest and downloadable MP4. Prefer resuming failed episodes from shot-level artifacts.

**Performance**: proposed pilot preview at 640×360, acceptance output at 1280×720 24 fps, later native 1080p and 9:16 recompose (not blind crop). Actual host/hardware capability and quality must be measured before treating targets as requirements. Studio may use a GPU-backed compositor, but if so **do not describe that as meeting P-L CPU-only evidence**. Render-time and memory budgets must be named per profile/host.

**Proposed CLI, not currently implemented:**

~~~bash
animalite studio doctor --json
animalite studio validate --project projects/milo-max/project.json
animalite studio render-shot --project projects/milo-max/project.json --shot blueprint-unfold --workspace work/studio
animalite studio preview --project projects/milo-max/project.json --shot blueprint-unfold
animalite studio assemble --episode projects/milo-max/episodes/marvel-engineer/episode.json
animalite studio report --episode marvel-engineer-pilot
~~~

Do not expose CLI commands until backed by one real execution service; CLI, API and future editor must call the same implementation. No shell injection, dynamic untrusted scripts, unsandboxed plugins, arbitrary file traversal or silent cloud uploads. Native subprocesses use argument arrays, bounded timeouts and cleanup.

---

## 9. Business/release tiers and acceptance gates

### Gate A — 12-second acting test (next milestone, highest priority)

**Scenario:** Milo has built a perfectly straight ground floor and a dramatically tilted upper floor. Owner notices, Milo presents a blueprint that is crooked due to a small crossed fold, owner removes fold to reveal a straight original drawing, shouts **“YOU IDIOT!”**, Milo proudly says **“IT'S AN ENGINEERING MARVEL!”**.

For the 12-second technical test, focus on the movement-rich middle: eye movement; two planted steps; torso/head turn; blueprint hold and transfer; visible unfolding and changed drawing; angry reaction and confident pose.

**Acceptance evidence**
- One **decodable 288-frame, exactly 12.000 s, 24-fps, 16:9 H.264 MP4**; prefer native 1280×720 after measuring feasibility, with 640×360 draft permitted but not mislabelled.
- Original characters retain face, colors, clothing and ratios; owner is distinct.
- Feet visibly plant; prop does not teleport; fingers/hands do not detach; blueprint fold is understandable; eye/body reactions are staged and timed for comedy.
- No severe body deformation, limb penetration, accidental identity changes, abrupt camera jumps or unintentional frame holds.
- Exact frame/source/provenance manifest; encoded output probed and decoded; durations tested; per-clip render time, peak memory and device truthfully reported.
- A separate reviewer signs off on the **actual MP4 at normal speed and frame-by-frame**, not only a script or static storyboard.

**Studio-specific human scoring proposal:** 1–5 per category: movement/weight, eye/face acting, prop interaction, composition/continuity, timing/clarity. Goal at least 4/5 in every category and zero blocking visible defects. This is **not** the v0.12 §12.0 8/10 test.

### Gate B — complete 55–60-second short

- Approved scene plan, 10–18 coherent shots, two reusable character rigs, actual expressions and sound.
- Finished 24-fps playable MP4 and 9:16 export; output 16:9 master if appropriate; no broken prop tracking or character swaps.
- Render revised *one shot* without invalidating unchanged shots or approved sound.
- Side-by-side quality review against the old motion-comic; publish only if clearly improved.
- Record new artwork/editing hours, rerenders, storage, runtime, any external generation spend and credit deductions.

### Gate C — 10-minute episode production

- **14,400 frames at 24 fps** for one 600-second 16:9 master; any clip transitions do not accidentally lengthen or shorten the timeline.
- Resumable scene/shot assembly, correct dialogue/audio mixing and shot-level cost accounting.
- Reusable library of at least the main recurring characters and multiple expressive action clips; no episode-long manual pose recreation for every frame.
- Correct scene transition, cancellation/restart, negative cases (missing assets, invalid joint track, render crash, encoded output corrupted), storage and performance data.
- Artist review and audience trial; do not promise a completion date or economic payback before evidence exists.

---

## 10. Implementation work packages and PR deliverables

**Each stage is a separately reviewable PR or small PR series.** Record which previous PR/branch is the base. Do not edit the existing CPU qualifying path merely to make Studio more convenient.

| Stage | Purpose | Deliverables / exit |
|---|---|---|
| S0 — owner/legal/branch gate | Stabilize baseline | Recheck PR #1/#2, confirm core status; owner addresses licensing NOTICE and DEC-0001; avoid automatic merge; document D-02/D-06 position; select development base |
| S1 — rig/renderer spike | **Prove motion is fixable** | One 5–12s real editable-rig animation with moving limbs/prop; compare >=2 candidates if feasible; factual performance/license evidence; recommended backend decision |
| S2 — Studio data contracts | Scriptable, repeatable inputs | Versioned schemas, frame/events/prop constraints, path/asset hash validation, migration/version tests; no renderer claims |
| S3 — character and motion library | Stable recurring actors | Editable Milo/Max rigs, expression/pose sets, action clips, foot contact/turn/reach/grasp; asset provenance; automated tests and actual rendered samples |
| S4 — adapter and shot renderer | First reliable export | Explicit Studio renderer profile, bounded frame streaming, reuse common media/lifecycle, audio hook, exact-frame MP4, immutable attempts and failure tests |
| S5 — Marvel Engineer | Production-quality proof | Complete 12s gate + 60s short; per-shot edit/re-render; human visual review and corrected movements |
| S6 — episode assembly | Practical 10-minute workflow | Shot cache, audio/captions/transitions, episode manifest, 16:9 master and 9:16 alternate, observable full export and recovery |
| S7 — optional smart production | Additional automation after core passes | Agent-assisted pose suggestion, reference performance retargeting, lip-sync, approved model path; separate rights/price/security gates |

**Gate rule:** S1 quality evidence comes **before** expensive S2–S6 implementation. If viable rigged acting cannot be demonstrated, report no-go or choose another renderer rather than building the rest of the stack.

**Provisional effort**: S0/S1 3–10 engineering days, S2/S3 8–22, S4/S5 10–25, S6 4–12, plus artist preparation and QA. These are broad planning bands and **not a commitment**; revise from the measured spike. Codex must not claim a phase passes because unit tests pass if observable acting remains poor.

### Scope of first Codex coding task

1. Read this document and the current source-of-truth requirements/AGENTS files.
2. Inspect current repo/PR state and explicitly report the correct base. If PR #1 is unmerged, **do not assume the implementation is on main**. Propose a small separate **stacked PR** based on the Package A branch, or wait for the owner to merge Package A. Do not silently merge PR #1/#2, or rewrite their history.
3. Carry out S1 rig/renderer **selection spike** in a sandbox/local environment. Do not ship new third-party engine sources or weights in Git. Use a tiny original Milo rig and original construction background.
4. Produce **one reproducible 5–12s real movement sample**: planted walking, turn, hold/release blueprint, reaction, and ideally visible unfold. Capture source project, commands, ffprobe metadata, runtime/resource observations and representative frames.
5. Compare candidate(s) and write an ADR with explicit evidence and unresolved questions. If an external tool cannot be installed or headless export is unavailable, document that rather than falsely claiming it was tested.
6. Open one **draft PR** with only the spike/prototype, ADR, relevant tests and citations to requirements. Keep GitHub Actions usage small; use repo's docs-only and draft PR conventions.
7. Stop at a quality/owner decision checkpoint. **Do not proceed automatically to S2–S7**.

---

## 11. Testing and release engineering

**Automated tests**
- Contract/schema versions, illegal curves/tracks, unknown assets, invalid bone names, NaN transformations, contradictory prop ownership.
- Frame timing and cadence, cut boundaries, exact expected frame counts, 16:9/9:16 composition, shot/episode durations.
- Pose clip continuity, foot-lock invariants, inverse kinematics reachability and joint limits.
- Hash consistency, cache invalidation/reuse, source output immutability, revision retention.
- Deterministic renderer sample frames on the *same pinned renderer/platform* when practical; disclose nondeterminism rather than asserting byte equivalence across OS/GPUs.
- Bounded-memory/chunked rendering, native child cleanup, cancellation, timeout, partial-output rejection and retry persistence.
- Media decode/probe, stream type/codec/size/framerate/color/audio, no truncated files, no unintended silent output.
- Rights and network policies, local offline mode, no unrequested model calls, cost log for any external generation.
- CLI/adapter tests through a single execution service; continue existing package tests unchanged.

**Human tests**
- View full clip with sound at normal playback and inspect key physical contacts frame by frame.
- Rate action clarity, comedy timing, expression, silhouette, continuity, spoken/text clarity and emotional relatability.
- Perform blind A/B comparison of old motion-comic and Studio output. **No assumption** that prettier backgrounds or higher resolution mean better acting.

**CI policy**
- Follow AGENTS.md / handoff v0.2. The existing PR #1 workflow is pull_request triggered with a docs-only lane and small default checks.
- No heavy benchmarks, model downloads or creator asset generation in PR CI.
- Batch changes; draft PR for exploratory code; only execute full tests on affected code and specified local host.
- Keep videos and model weights out of commits unless tiny fixtures are explicitly approved; provide stable artifact links and hashes.
- Never use benchmark data from generic GitHub-hosted CI as proof of v0.12 P-L performance.

---

## 12. Legal, business and security decisions to settle

| Decision / risk | Owner or reviewer action | Constraint now |
|---|---|---|
| PR #1 NOTICE copyright-holder | Repo owner supplies actual legal notice | Do not invent author identity |
| DEC-0001 PolyForm Noncommercial | Repo owner accepts/revises; legal review as appropriate | Current license proposal doesn't automatically authorize all future monetized creator/business uses |
| Third-party code/art/music/model rights | Verify each component and output use case; retain notices; verify contributors' relicensing rights | No implicit redistribution or commercial rights |
| D-02 and AT-055/056 | Owner locks actual P-L hardware and thresholds before qualification | Studio visual demo is not a learned CPU pass |
| D-06 / learned runtime admissions | Rights-holder/owner approval with artifact digests and specific purposes | RIFE learned execution remains gated until admitted |
| Studio CPU/GPU/device policy | Owner approves Studio-specific target hardware and spend | GPU-backed Studio is allowed only as a separately labeled profile; it cannot qualify CPU-only claims |
| “MARVEL ENGINEER” and recognizable Thor hammer | Owner reviews trademark/creative asset risks before public monetization | Preserve requested pilot title for private evaluation; do not silently substitute branding. Consider an original lightning/hammer motif for commercial release if needed |
| Global audience character identity | Owner approves design bible and voice/language policy | Milo/Max must be original, no Chaplin costume/signature imitation |
| Externally hosted inference/services | Owner approves price/rights, provider, scopes, asset retention and upload | No unexpected calls/purchases or cloud fallback |
| Budget | Owner decides cash/compute limits; Codex reports actual cost/time | “20% of ChatGPT weekly quota” is **not a measurable/enforceable repo-specific hard limit** here |

**Security and privacy:** media and prompt assets may be sensitive. Treat untrusted project files as data, sandbox any scripts, do not execute arbitrary file-provided commands, limit paths and resource use, pin dependencies, hash downloaded executables, never embed API keys in project manifests, never auto-upload assets. Record opt-in for external providers.

---

## 13. Usage-aware Codex operating protocol

The owner wishes to preserve ChatGPT's weekly allowance. **No agent has an API to enforce a hard 20%-of-weekly-ChatGPT-usage limit for one repository here.** Do not promise a mathematical cap. Use bounded work units instead:

1. One work package per Codex task, with explicit scope and a **stop point**.
2. Read relevant files only; reuse existing repo state; avoid rediscovering all docs on each pass.
3. Prefer local deterministic tests and cached assets; do not re-generate images/video or re-download toolchains repeatedly.
4. No paid cloud inference, paid video services, purchases or large model downloads without explicit owner approval.
5. Record per task: chosen base/head SHAs, changed files, tests run (with real results), wall-time, machine profile, render seconds, model/AI calls where measurable, API/credit cost where measurable, unresolved blockers.
6. Do not substitute invented token or weekly percentage figures for unavailable billing data.
7. Fail fast on architecture/rights/hardware blockers; do not bury them inside endless repair loops.
8. Do not merge automatically or post many small commits for every review message. Use one coherent implementation + a consolidated verification report.

### Copy/paste Codex kickoff request

> Repository: https://github.com/sivaperuman/AnimaLite  
> Read docs/strategy/ANIMALITE_STUDIO_CODEX_HANDOFF_v1.md in full and check the current status of PRs #1 and #2. Follow the authoritative v0.12 source document, handoff v0.2 and AGENTS.md on the correct branch. Do not weaken CPU sparse-anchor requirements or claim the current fixture/RIFE path passes AT-055/056.  
>  
> **TASK: S1 rig/renderer feasibility spike only.** Find the appropriate code base (PR #1 is currently open and not merged), research/compare OpenBone, Rigby2D, Godot or a minimal controlled fallback, and implement the smallest scriptable animation sample that visibly improves **planted walking, expressions and hand-to-blueprint interaction** in the 12-second Marvel Engineer technical sequence. Prefer a reusable asset/rig format and a local reproducible render. Provide tested environment, exact frame counts, a real playable MP4, screenshots, metrics, rights and known limitations.  
>  
> Create a small **draft pull request** containing the comparison ADR, minimal prototype, reproducible commands and relevant tests. No heavy UI, episode backend, cloud provider, model download or paid usage; no merges/owner licensing decisions. Do not trigger full production CI or run wide benchmarks. Stop after the S1 evidence and request owner/quality review before the next stage.

---

## 14. Completion and change-control checklist

Before calling **Studio MVP ready**, there must be evidence that:
- [ ] Owner-approved scope/addendum and license/rights decisions are recorded; original v0.12 claims remain separate.
- [ ] Correct baseline branch/PR dependencies are resolved and not obscured.
- [ ] Editable and reusable rig exists for Milo and Max with original layer artwork.
- [ ] Walking/turning/looking, face states, grasp/release, prop handling and animation timing are demonstrably better than the old trial.
- [ ] 12-second test is accepted by human reviewers on actual decoded footage.
- [ ] 60-second short works with sound, exact frame count and revisions.
- [ ] Project/shot/episode schemas validate; frame and shot metadata are complete.
- [ ] Source, render attempts, outputs, audio and provenance are hashed and versioned.
- [ ] Batch rendering and 10-minute episode assembly recover from failures without rerendering unrelated shots.
- [ ] Actual production hours, resource usage, failures and any credits are documented; no fabricated ROI or weekly quota percentage.
- [ ] Release/export package includes relevant third-party license and content-rights checks.
- [ ] Documentation clearly distinguishes authored-rig animation from qualified learned CPU interpolation.

**End-state:** A creator can prepare a structured story, reuse Milo/Max rigs and staging, direct natural character actions and jokes, preview/edit individual shots, and export consistent Shorts or 10-minute episodes locally with bounded costs and verifiable output—**without claiming that animation is automatic or that the separate v0.12 learned-model gate has passed.**
