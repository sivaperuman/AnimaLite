# Marvel Engineer acting test

This 12-second silent scene tests whether two original cutout characters can carry a joke through motion. The crooked floor at the left of the site appears on Milo’s folded drawing. The owner takes the sheet, opens the cross-fold, sees the straight drawing and points at Milo. Milo answers with his chest out and a grin.

## Reproduce on Linux

Use Package A’s Python 3.11 environment. Install FFmpeg and FFprobe with libx264 on PATH. The Godot comparison also needs the external Godot 4.6.3 executable named `godot`. The renderer itself runs locally with a dummy display. The spike dependencies stay in the development environment.

```sh
python3.11 -m venv .venv
.venv/bin/pip install -e '.[dev]' -c constraints/dev-linux-cpython311.txt
.venv/bin/pip install -r spikes/studio_s1/requirements.txt
.venv/bin/python -m pytest -q spikes/studio_s1/test_performance.py
.venv/bin/python spikes/studio_s1/render.py --backend godot --workspace work/s1
.venv/bin/python spikes/studio_s1/render.py --backend native --workspace work/s1
```

Each command prints a new attempt directory. Open its `marvel-engineer.mp4`. For a 640×360 rehearsal add `--width 640`. Both modes rasterize vectors at the selected resolution. `settings.json` identifies the source files, toolchain and output settings. `manifest.json` records the decoded result, timing and ordered input-to-encoder RGB hashes for frames 0 through 287. Errors retain a diagnostic in the attempt directory. Retrying the command creates a fresh directory. The existing `animalite` CLI and the benchmark have separate inputs and evidence.

## Direct the scene

| Frames (inclusive) | Performance to inspect |
| --- | --- |
| 0–31 | Owner’s pupils lead the head up to the tilted floor. Milo shifts his weight before stepping. |
| 32–80 | Milo swings the far boot and plants it, then swings the near boot. Watch the supporting sole against the ground as each knee flexes. |
| 81–129 | Milo turns and offers the folded plan with both hands. The camera starts closing in as the owner reaches. |
| 130–168 | Both touch the near corner first. Ownership changes at 143. The owner takes the weight before Milo withdraws the second hand. |
| 169–210 | Two grips separate as the crease opens. Compare the two floors on the drawing before and after the snap. |
| 211–287 | Owner recoils and points. Milo waits through the rebuke, straightens and touches his chest. |

Edit `milo.svg` or `owner.svg` to change the head, torso or shoe. Each named group uses a local pivot. The two-link chains and attachments live in `rigs.json`. The timeline in `performance.py` sets world-space foot locks, wrist targets, gaze, facial acting and camera curves at integer frame indices. Both backends receive the same targets and art. The blueprint stays in a single coordinate system through the transfer. `artwork.py` draws its two floors and crease from a continuous unfold parameter. The set in `site.svg` can be reused independently.

The Godot experiment drives actual Bone2D chains and the engine’s two-bone IK modifier, then rasterizes the posed vector layers using its CPU image API. The Python comparison solves each chain analytically and streams resvg output. Neither path requires a display, weights, generated stock footage or a video service.

The draft PR includes a [decoded frame sheet](../../docs/verification/studio-s1/contact-sheet.webp), the [four run records](../../docs/verification/studio-s1/runs.json) and the [backend decision](../../docs/decisions/STUDIO-S1-rig-feasibility.md). The shared workspace review player offers the MP4s and raw evidence ZIP. Repository hosting of the videos is pending.
