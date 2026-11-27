# DEC-0004 — Media pipeline and encoder settings

* **Status:** Accepted
* **Deciding role:** implementation
* **Affects:** §12.0 core output, NFR-019, MR-009, handoff v0.2 rules 5, 6, 7

## Decision

**FFmpeg is external.** `ffmpeg` and `ffprobe` are resolved from `PATH` or from
`ANIMALITE_FFMPEG` / `ANIMALITE_FFPROBE`. Nothing is bundled or vendored. The
resolved path, version and full build `configuration:` string are recorded, and a
GPL-configured build raises a warning in `doctor`.

**Every native call uses an argument array.** No command string is ever passed to
a shell, so a path containing shell metacharacters is inert. A test asserts this
with a directory named `a dir; touch pwned`.

**Output settings are fully pinned** — no FFmpeg default is relied on:

| Setting | Value |
| --- | --- |
| Geometry | 640×360 (preview 320×180) |
| Codec / profile / level | `libx264` / `high` / `3.1` |
| Pixel format | `yuv420p` (even dimensions enforced by the contract) |
| Rate control | CRF 18 (preview 23), `preset medium` |
| Colour | `bt709` primaries / transfer / matrix, `tv` range |
| Frame timing | `-r 24 -vsync passthrough` |
| Container | MP4, `+faststart` |
| Threads | from the profile's `ThreadBudget.encoder_threads` |

All of it is serialized into the attempt record and covered by
`settings_digest()`.

**Frames stream.** The adapter yields one animation frame at a time; the cadence
expander holds each frame `hold_factor` times; the encoder writer pipes each
delivery frame into stdin and drops it. No stage accumulates the clip, so peak
memory does not scale with duration.

**Publish only after decode validation.** The encoder writes into the attempt's
`work/` directory. `ffprobe -count_frames` then verifies geometry, pixel format,
*decoded* frame count, average frame rate, duration (1 ms tolerance, against a
41.7 ms delivery frame) and non-zero size. Only then is the file moved into
`output/` with `os.replace`, which is atomic within the attempt directory. A
partial encode is never published, and an existing published file is never
overwritten.

**Anchors are decoded through the same FFmpeg** with a pinned scaler
(`scale=W:H:flags=bicubic`), so input normalization is repeatable (MR-009) and
there is no second image-decoding dependency.

## Why the tolerance is 1 ms

Container duration is stored with limited precision, so exact float equality
would be flaky. One millisecond is roughly 1/42 of a single delivery frame at
24 fps: it accepts container rounding while rejecting any real frame-count or
cadence error. The *exact* six-second guarantee is asserted separately, on
rationals, in the contract (`Fraction(144, 24) == 6`).

## Reversal

Changing any pinned setting changes `settings_digest()`, which is the point:
outputs produced under different settings are not comparable and the record says
so.
