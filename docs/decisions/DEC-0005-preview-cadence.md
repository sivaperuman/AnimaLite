# DEC-0005 — Preview cadence

* **Status:** Accepted (measurement clarification; changes no target)
* **Deciding role:** implementation
* **Affects:** §12.0 warm preview row, CR-004, A-07, D-09

## Decision

The preview output is **320×180, 36 animation frames at 12 animation fps,
expanded by two-frame holds into 72 delivery frames at 24 fps = exactly 3.000
seconds**.

## Why this needed a decision

§12.0 specifies the preview as "a playable 3-second 320×180 preview, 12 animation
fps". It states the *animation* cadence but not the delivery frame rate, so the
delivery stream had to be chosen.

Applying the project cadence policy (CR-004: duplication from 12 unique fps to 24
delivery fps, the A-07 benchmark convention) keeps the preview consistent with
the final output, so preview and final timings differ in resolution and length
rather than in cadence semantics. The alternative — delivering the preview at
12 fps with no holds — would have made the two measurements structurally
different and complicated any comparison.

## What this does not change

* No §12.0 target changes. The warm preview p95 ≤ 15 s target is untouched and
  still unapproved (D-02).
* Frame accounting still reports source, synthesized and duplicated counts
  separately for the preview, so the 36 duplicated delivery frames are never
  presented as new temporal information.
* D-09 remains the sole production-cadence approval decision. If D-09 replaces
  the 12→24 duplication convention, this decision follows it automatically
  because the preview simply uses the project `CadencePolicy`.

## Verification

`tests/test_cadence.py::test_preview_output_is_exactly_three_seconds` asserts the
rational duration; `tests/test_media_end_to_end.py::test_the_preview_spec_renders_exactly_three_seconds_at_320x180`
decodes a real encoded preview and checks 72 frames at 3.000 s.
