# AnimaLite

**Status: Package B in progress — one learned CPU model (RIFE via ncnn) is now
integrated behind the common adapter interface. No §12.0 performance target has
been measured on an approved host, and no qualification has been attempted.**

AnimaLite is the implementation of the *Frame-Conditioned 2D AI Video Production
System* requirements (v0.12). Its objective is to produce a short, useful video
clip from 2–4 approved frames on CPU or lower-spec hardware, with a measured and
honestly reported turnaround.

This repository currently contains the foundation for that work: typed contracts,
a local execution service, a CPU media pipeline, a host inventory command, a
benchmark harness, and a deterministic **fixture** adapter used to exercise the
pipeline end to end without any model weights or private artwork.

## What works today

| Capability | State |
| --- | --- |
| Installable `animalite` package and CLI (`animalite`, `python -m animalite`) | Working |
| Typed, versioned contracts (anchors, shot intent, engine profile, job/attempt, capabilities, resource estimate, output manifest, measured results, host inventory) | Working |
| Local execution service with the §6.3 lifecycle (validate / estimate / submit / status / cancel / collect / capabilities) | Working |
| Immutable attempt directories, finite timeouts, process-group cleanup, retained failure diagnostics, retry-as-new-attempt | Working |
| CPU media pipeline: anchor decode, cadence expansion, streaming CPU encode, decode validation before publish | Working |
| Reproducible synthetic fixture generator and fixture adapter (deterministic, **not** learned) | Working |
| Host/environment inventory (`animalite doctor`) | Working |
| Benchmark harness: run ledger, stage/end-to-end timing, process-group memory where supported, median / nearest-rank p95 / maximum, failed-and-missing-run retention, qualification eligibility evaluator | Working |
| Learned CPU temporal model (`rife-ncnn-v4.6-cpu`, CPU-only) | Implemented — runtime installed out of band and hash-verified, but **execution is blocked** until a rights decision is recorded (DEC-0016) |
| Classical warp/flow comparator (`classical-warp-baseline`, block matching, **not** learned) | Working — the non-learned reference the learned candidate is measured against (DEC-0015) |
| §12.0 qualification measurements (AT-055 / AT-056) | **Not run** — Package C, and blocked on the D-02 host approval |
| Web/review UI, project storage, queue, export, cloud or GPU execution, training | **Out of scope** for this stage |

## What this repository does *not* claim

* **No qualified learned-model performance has been demonstrated.** A learned
  model has run on an unapproved container, and its output was measurably not a
  cross-fade — an engineering result, not a §12.0 result, and not on its own
  proof of an advantage over a non-learned method.
  `fixture-synthetic` remains a deterministic anchor blend and is labelled
  non-qualifying everywhere; MR-018 excludes cross-fades from learned temporal
  capability. A learned render is *also* not qualification evidence on its own,
  and its manifest says so with the actual reasons.
* **The model's licence position is unresolved, and it now blocks execution.**
  RIFE's code and weights are both MIT upstream, but the ncnn-format conversion
  chain has not been reviewed. The learned profile therefore does not run at all
  without an approved admission record covering its exact artifact digests and
  the run's purpose — missing, pending and rejected all block, before any
  invocation, with no development bypass. The comparator and the fixture
  adapter execute no third-party artifact and are unaffected. See
  `docs/decisions/DEC-0016-execution-admission.md`,
  `docs/decisions/DEC-0013-rife-licence-position.md` and
  `docs/licensing/admissions/README.md`.
* **No timing here is a P-L result.** Section 12.0's warm/cold/preview targets
  are *proposed* engineering targets awaiting D-02 approval. Any number produced
  on a developer or hosted machine is exploratory. The benchmark evaluator
  refuses to emit a qualifying verdict when the host is unapproved, the adapter
  is non-learned, an observation is missing, or human quality evidence is absent.
* **No phase gate has passed.** Phase 0 (D-01/D-02) and the Phase 1 CPU
  feasibility gate remain open.

## Requirements and prerequisites

* Python 3.11–3.13 (development baseline: CPython 3.11).
* An **externally installed** FFmpeg providing `ffmpeg` and `ffprobe` on `PATH`
  (or pointed at by `ANIMALITE_FFMPEG` / `ANIMALITE_FFPROBE`). FFmpeg is not
  bundled or vendored here; see `THIRD_PARTY_NOTICES.md` and `docs/licensing.md`.
* No GPU and no network access at run time.
* The **fixture** and **comparator** profiles need no weights. The **learned**
  profile needs the pinned RIFE/ncnn runtime, installed out of band — nothing is
  committed and CI never downloads it. `animalite runtime fetch` prints the
  pinned steps; `animalite runtime fetch --install` performs a bounded,
  digest-verified, atomic install; `animalite runtime status` reports installed
  / verified / compatible / admitted separately, and executes nothing.
* Installing the runtime does **not** permit running it. Executing it also needs
  a recorded admission decision (`docs/licensing/admissions/README.md`).

## Install and verify

See [docs/verified-commands.md](docs/verified-commands.md) for the exact commands
that were executed for this branch, with their observed output.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]" -c constraints/dev-linux-cpython311.txt

animalite --help
animalite doctor --json          # host + tool inventory; inventory, not approval
python -m animalite doctor       # equivalent fallback entry point
```

## One small local example

Generate the deterministic synthetic anchors, then render them through the real
CPU media path:

```bash
animalite fixtures generate --out-dir work/fixture --clip fixture-two-anchor
animalite render \
  --profile fixture-synthetic \
  --anchors work/fixture/fixture-two-anchor/anchors.json \
  --workspace work/ws \
  --json
```

The result is a 640×360 H.264/MP4 file: 72 animation frames at 12 animation fps,
expanded by two-frame holds into 144 delivery frames at 24 fps — exactly 6.000
seconds. The published manifest records the source, synthesized and duplicated
frame counts separately, and carries
`is_qualifying_evidence: false`.

`--profile` is mandatory: rendering never selects an engine implicitly, so a
fixture render can never be mistaken for the future learned model.

## Quick check

```bash
ruff check . && ruff format --check .
mypy
pytest -m "not slow"        # contract, failure-path and statistics tests
pytest                      # adds the tiny end-to-end media integration test
```

Media tests report *pending* rather than passing when FFmpeg is unavailable.

## Repository layout

```
src/animalite/contracts/   typed, versioned job/profile/asset/result contracts
src/animalite/errors.py    exception hierarchy and stable validation codes (leaf)
src/animalite/proc.py      child-process group management (leaf)
src/animalite/resources.py thread budget and peak-memory sampling (leaf)
src/animalite/core/        validation, execution service, attempt store
src/animalite/adapters/    adapter protocol, fixture (non-learned) and RIFE/ncnn (learned) adapters
src/animalite/media/       ffmpeg discovery, cadence, streaming encode, probe validation
src/animalite/bench/       benchmark runner, ledger, statistics, eligibility evaluator
src/animalite/hostinfo/    host and tool inventory
benchmarks/                dataset manifests, host records, target sets, evidence bundles
docs/requirements/         the v0.12 source document and a labelled CPU-stage extract
docs/decisions/            durable implementation decisions
docs/verification/         requirement / AT / evidence mapping
```

## Licensing

AnimaLite's own source code is licensed under the
[PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0)
(SPDX: `PolyForm-Noncommercial-1.0.0`). The complete, unmodified license text is
in [`LICENSE`](LICENSE).

AnimaLite is **source-available**, not OSI open source: a commercial-use
restriction does not meet the
[Open Source Definition](https://opensource.org/osd). PolyForm Noncommercial
permits noncommercial purposes and certain organizational uses, including
educational and government institutions irrespective of funding; it is not an
absolute prohibition on every revenue-related activity. Read the license text
rather than this summary.

This license covers **only** the original AnimaLite software in this repository.
Third-party dependencies, the separately installed FFmpeg, and any model code or
weights added later keep their own terms — recorded in
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) and discussed in
[`docs/licensing.md`](docs/licensing.md).

**Commercial permission** is a project-owner decision. Requests are made by
opening a GitHub issue in this repository titled `Commercial use request`; no
contact address, price or standard commercial terms exist yet, and none is
implied here. The maintainer cannot unilaterally relicense contributions made by
others, so any commercial arrangement needs legal review — see
[`CONTRIBUTING.md`](CONTRIBUTING.md).

The copyright-holder name in [`NOTICE`](NOTICE) is an open metadata item
(`<COPYRIGHT-HOLDER-PENDING>`), deliberately left for the owner to supply.

## Working agreement

Engineering and review instructions live in [`AGENTS.md`](AGENTS.md);
[`CLAUDE.md`](CLAUDE.md) imports them. Durable implementation decisions are
recorded in [`docs/decisions/`](docs/decisions/).

## Story to video in ChatGPT

With this checkout and an image-generation tool available, ask: “Animate this
story with AnimaLite: Max punches a ticket, looks out of the bus, and recognizes
the driver riding a bicycle.” The development session performs the following steps:

1. Break the story into ordered shots of 1–6 whole seconds. Pick one camera setup
   per shot and describe the action and its payoff. Match any supplied characters
   and references. For a one-minute request, budget exactly 60 seconds across shots.
2. Generate the actual opening and ending images for each shot in ChatGPT. Use
   the opening image as the visual reference for later poses. Add up to two
   intermediate poses where anticipation, contact or a reaction matters. Keep
   the camera and background registered. Generate new artwork for new shots.
   Save the selected PNG, JPEG or WebP stills alongside the storyboard. If the
   session cannot generate images, report that dependency or use supplied stills.
3. Write a storyboard such as the one below. Frame indices use the 12 fps
   animation timeline. Repeat an image at two indices for a held pose.
4. Run the command and deliver the printed MP4 path. Each run retains the
   shot attempts in its own directory. Check the result visually before delivery.

```json
{
  "story": "Max punches a ticket and spots the driver outside.",
  "shots": [{
    "action": "Max holds the ticket still, then looks out the window.",
    "seconds": 3,
    "timing": "ease-in-out",
    "poses": [
      {"frame": 0, "image": "max-start.png"},
      {"frame": 15, "image": "max-start.png"},
      {"frame": 35, "image": "max-reaction.png"}
    ]
  }]
}
```

```bash
python -m animalite story-render storyboard.json --profile classical-warp-baseline
```

With the classical renderer, optional `ease-in-out` timing starts and lands each
movement gently. Omit it for linear timing.

The command fits images into 640×360 without stretching, renders each shot
through the execution service and joins them with hard cuts into one
24 fps H.264 MP4. Paths are resolved relative to the storyboard. The baseline
warps and blends input poses; it can ghost on large changes. Image creation is
performed by ChatGPT in the session. The standalone CLI takes local artwork.

### Camera and character voices

Set a shot's `camera.angle` to the viewpoint you want, such as “eye-level
medium shot of Max” or “over Max's shoulder toward Milo on the bicycle”.
ChatGPT draws the poses from that viewpoint. Start a new shot and generate
its poses when changing angle in an illustrated shot. For a continuous orbit,
use a 3D stage as described below.
Zoom is animated at 24 fps: use 1.0 for the whole frame or up to 4.0 for a
tighter crop. A larger ending value pushes in; a smaller one pulls back.
Set `focus_x` and `focus_y` between 0 and 1 to anchor the move near a face
or prop (0.5, 0.5 by default).

Assign recurring English voices at storyboard level. Each shot may include
dialogue timed in milliseconds from the start of that shot:

```json
{
  "story": "Max notices who is cycling beside the bus.",
  "voices": {"Max": "rms", "Milo": "awb"},
  "shots": [{
    "seconds": 4,
    "action": "Max spots the driver and stops punching tickets.",
    "camera": {"angle": "eye-level medium shot", "zoom_start": 1, "zoom_end": 1.4,
               "focus_x": 0.35, "focus_y": 0.4},
    "poses": [{"frame": 0, "image": "max-start.png"}, {"frame": 47, "image": "max-end.png"}],
    "dialogue": [{"character": "Max", "start_ms": 450, "text": "Who's driving?"}]
  }]
}
```

Text uses FFmpeg's optional offline Flite filter (voices `awb`, `rms`, `slt`,
`kal`, `kal16`); the installed FFmpeg build must include the chosen voice.
For a recorded performance, another language, or a preferred TTS provider,
supply a local WAV, MP3 or FLAC with `{"character":"Milo","start_ms":500,
"audio":"voices/milo.wav"}`. Recorded lines need no voice assignment. If both
text and audio are supplied, the recording is used. Silence and overlapping
lines follow the timeline. A line that overruns a cut is reported with its shot
and character. The output includes one mono AAC track when dialogue is present.
Runs retain normalized voice recordings for replay.

### Automatic lip sync and continuous 3D rotation

Try the included two-character scene from an AnimaLite checkout:

```sh
python -m animalite story-render examples/orbit-dialogue.json --profile classical-warp-baseline
```

The example uses Blender 4.3+ (the `blender` executable on PATH) and FFmpeg
with Flite. It renders a stationary dialogue shot and then a complete camera
orbit with two separately timed voices. On the built-in stage, each named
actor has its own mouth rig. Supply dialogue as text or recorded audio as above.
AnimaLite measures each speaker's isolated WAV at 24 fps and uses loudness and
spectral bands to estimate jaw opening, rounding and spreading. Silence returns
that character to rest; overlapping speakers animate independently. This is
acoustic animation rather than a phoneme-alignment or face-detection model.

**Illustrated shots.** Ask the image generator to leave a clean mouth area in
each pose. In that shot set e.g. `"mouths": {"Max": {"at": [0.38, 0.54],
"end": [0.39, 0.54], "width_px": 22, "ink": "#382531"}}`. Supply the center
of the mouth on the padded 640×360 canvas in normalized coordinates.
The optional end point follows linear head motion. Use a new shot for complex
head turns. FFmpeg with libass draws the mouth before zoom; existing storyboards
without a mouth rig retain their drawn expressions. Omit a mouth for an offscreen
speaker. No per-word or per-frame mouth keys are required.

**3D shots.** Replace the shot's `poses` with `stage`. Use named `actors`
for the built-in stick figures or point `model` at a self-contained GLB 2.0
scene. For an imported speaking character, set e.g.
`"bindings": {"Max": "MaxFace"}`; that mesh needs the relative shape keys
`AL_open`, `AL_round`, and `AL_wide`. By default, the stage uses Blender's solid-material
Workbench renderer. It renders actual meshes with occlusion and parallax.
For exact character or set designs, provide their geometry and material colors.
Generated flat artwork alone supplies no back or side geometry.

`orbit.target` is a Blender-world XYZ look-at point (Z up); `radius` uses scene
units. The `yaw`, `pitch` and `roll` pairs are start/end angles in degrees.
Yaw starts on the negative Y axis. Use `[0, 360]` for a continuous revolution,
`[30, -60]` to reverse direction, or matching values for a fixed angle.
Interpolation follows the specified angular travel at every delivery frame.
Use `camera.zoom_start/end` for a lens change during the orbit.
Each stage shot lasts 1–6 seconds at 24 fps. Stage and illustrated shots can share
a 640×360 storyboard. Blender is needed only for stage shots.

### Directing a stylized 3D performance

Add `"cinema": {}` inside a shot's `stage` to switch on the CPU Cycles renderer.
Built-in actors gain articulated heads, brows, eyes and shoulders, and materials
for skin, eyes, fabric and metal. Imported GLB scenes keep their own meshes and
materials. Choose a studio floor, a workshop with shelves and glazed jars, or
the imported set. Daylight and sunset presets use area lights for the key,
fill and rim.

Try the three-second, two-character example from the repository root:

```bash
animalite story-render examples/workshop-reaction.json \
    --workspace work/workshop --profile classical-warp-baseline
```

| Storyboard field | Direction |
| --- | --- |
| `height` | Top-level delivery height. Default 360. Use 720 or 1080 for a fully staged 16:9 story. |
| `stage.cinema.set` | `studio` (default), `workshop`, or `asset` for an imported GLB with its own set. |
| `stage.cinema.lighting` | `daylight` (default) or `sunset`. |
| `stage.cinema.focus_distance` | Two distances from the camera in scene units. Use equal values for fixed focus or different values for a focus pull. Omit for deep focus. |
| `stage.cinema.f_stop` | Aperture from 0.7 to 32. Lower values give a shallower depth of field when focus is enabled. |
| `stage.cinema.ease_camera` | Ease the orbit, zoom and focus into and out of a move. Set to false for constant-rate travel. |
| `stage.cinema.shutter` | Motion blur exposure in fractions of a frame, from 0 (default, off) to 1. |
| `stage.cinema.samples` | Sampling budget per pixel, from 1 to 128 (default 12). Higher values cost more CPU time. |
| `stage.cinema.denoise` | Default true. Uses Cycles OpenImageDenoise where available, or FFmpeg's spatial non-local means filter. |
| `stage.actors.<name>.costume` | `forelock` (default) or `cap`. |
| `stage.actors.<name>.acting` | Ordered poses timed by `at`, from 0 (first frame) to 1 (last frame). |

For a reaction, direct the **eyes first**, turn the head a beat later, and hold
the final pose so the audience can read it. Each pose sets `head_turn`,
`head_tilt`, `gaze`, `brow`, `smile` (negative for a frown), and `squash` in the range −1 to 1, and
`blink` and `raise_hand` in the range 0 to 1. Omitted controls return to
neutral at that pose. Values ease between poses and hold outside them.
The speaker's audio drives the mouth independently. These acting controls
target the built-in cast. Custom characters need their own modeled geometry,
rigs and animation in the GLB.

### Full-body acting and prop handoffs

Render the silent, fixed-camera biscuit gag from the repository root.

```bash
animalite story-render examples/biscuit-handoff.json \
    --workspace work/biscuit --profile classical-warp-baseline
```

Use a cinematic stage with built-in actors. A storyboard-level `cast` entry
sets skin, shirt, costume, overall `size`, and `limb_scale`. A shot selects the
design with `"design": "Milo"` and positions it with `x` and `y`. Each actor
can select a reusable `move` or supply a `motion`. Four built-in moves are
available: `peek`, `recoil`, `offer`, and `sidestep`. A storyboard can add or
override named `moves`. A nonempty shot-local track replaces that track in
the selected move. Saved shot data contains the expanded design and tracks.

Beats use **one-based delivery frames** at 24 fps. Each beat moves from its
previous value at `frame` to its destination at `end`. Equal start/end frames
make an immediate change. Gaps hold the previous pose. Tracks can overlap
one another. Beats on the same track must be ordered and disjoint. Use the
default smooth easing or `"ease": "linear"`.

| Track in `motion` | How to direct it |
| --- | --- |
| `body` | Set a pelvis `offset` from rest in actor-local units, a sideways spine `lean`, and a torso `turn` in degrees. |
| `left_foot`, `right_foot` | Move an ankle by an offset from its planted position. Use two beats to lift and land a foot. Grounded feet stay in place as the pelvis moves. |
| `left_hand`, `right_hand` | Reach a `target` and optionally set wrist `rotation` in world XYZ degrees. Elbows and knees use a two-segment IK solve. Left and right belong to the actor. |
| `eyes`, `head` | Give each a target and its own timing. To lead a reaction with the eyes, start the head beat several frames later. |

A `target` can specify a world `point`, an actor-relative `local` point, an
`actor` to look at, or a `prop` with an optional named `grip`. An optional
world-space `offset` adjusts the aim. Completed reaches and looks keep
tracking a moving target. Facial acting and spoken mouth cues still work.

Stage `props` can be a `biscuit`, `tin`, `ball`, or `box`. Give each a
world `position`, optional initial XYZ `rotation` in degrees, color, size and
local grip coordinates. Every prop has a `center` grip. In the example the
two hands meet opposite edges of the biscuit:

```json
{"frame": 43, "action": "grasp", "actor": "Milo", "hand": "left", "prop": "Biscuit", "grip": "edge"}
```

At frame 91 a `handoff` names **Max's receiving hand** and the `other` grip.
The current owner supplies the donor. The prop keeps its world pose at the
transfer and subsequently follows the receiving wrist's translation and
rotation. A `release` leaves the prop at its last world pose. A hand holds one
prop at a time. Schedule the reach to arrive on the contact frame. The renderer
rejects missed grips (over 0.002 scene units), unreachable limbs and circular
hand/prop targets with the offending frame. This workflow uses authored contacts.
Free-falling objects, collisions and custom imported skeletons need separately
authored animation.

### Harbour 2D performance demo

Milo waves, walks to the bus, calls out to Max, then runs to hand over a lunchbox.
This 15-second example draws original 2D poses at 1280×720 and 60 fps. The feet
stay fixed during ground contact. AnimaLite derives mouth shapes from the spoken
line, and the footsteps follow the same landing times as the animation.

From the repository root, with AnimaLite installed and FFmpeg built with Flite,
libx264 and AAC support, run

```bash
python -m pip install pycairo scipy
python examples/harbour/render.py work/harbour.mp4
```

The renderer uses Pycairo and the DejaVu Sans font for drawing. If Pycairo is
installed in a separate system Python, pass `--drawing-python /usr/bin/python3`.
