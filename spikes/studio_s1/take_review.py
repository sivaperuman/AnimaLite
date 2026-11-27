"""Post-encode visual review for the fixed 24 fps S1 shot and its frame ranges."""

import time
from itertools import groupby

import numpy as np
from PIL import Image, ImageDraw

from animalite.proc import run_capture

# Frame numbers address the authored performance, including when a take starts mid-shot.
BEATS = {
    48: "First stride",
    80: "Foot plant",
    130: "First contact",
    143: "Transfer",
    177: "Unfold",
    197: "Read the drawing",
    201: "Look across",
    228: "Point",
}
LUMA_SIZE = (64, 36)
CELL_SIZE = (256, 144)
FPS = 24


def picture_notes(gray, first):
    """Return half-open source-frame spans. Tests are tuned for this uncut, lit set."""
    findings = []

    def mark(kind, start, stop):
        findings.append({"kind": kind, "start_frame": first + start, "stop_frame": first + stop})

    def spans(flags):
        for active, indices in groupby(enumerate(flags), key=lambda item: item[1]):
            if active:
                group = [index for index, _ in indices]
                yield group[0], group[-1] + 1

    # Two luma percentiles keep a dark detailed drawing from looking like a blank frame.
    dark, light = np.percentile(gray, (5, 95), axis=(1, 2))
    for start, stop in spans((light <= 24) & (light - dark <= 8)):
        if stop - start >= 6:
            mark("near_black", start, stop)

    signed = gray.astype(np.int16)
    delta = np.abs(np.diff(signed, axis=0)).mean(axis=(1, 2))
    for start, stop in spans(delta <= 0.08):
        # N consecutive quiet transitions connect N+1 frames.
        if stop - start + 1 >= FPS:
            mark("near_still", start, stop + 1)

    # A one-frame excursion can sit inside the shot or at a preview boundary.
    # For an interior excursion the picture must return close to its preceding state.
    for i in range(1, len(gray) - 1):
        if min(delta[i - 1], delta[i]) >= 18 and np.abs(signed[i + 1] - signed[i - 1]).mean() <= 4:
            mark("flash_candidate", i, i + 1)
    if len(delta) >= 4:
        if delta[0] >= max(18, 5 * max(delta[1:4])):
            mark("edge_jump", 0, 1)
        if delta[-1] >= max(18, 5 * max(delta[-4:-1])):
            mark("edge_jump", len(gray) - 1, len(gray))
    return sorted(findings, key=lambda row: (row["start_frame"], row["kind"]))


def review_frames(shot, notes):
    """Always include range endpoints, then acting beats and up to four flagged frames."""
    labels = {shot.start: "Range start", shot.stop - 1: "Range end"}
    labels.update({f: name for f, name in BEATS.items() if f in shot})
    flagged = {}
    for note in notes:
        f = note["start_frame"]
        if f not in flagged and len(flagged) == 4:
            continue
        flagged.setdefault(f, []).append(note["kind"].replace("_", " "))
    for f, names in flagged.items():
        labels[f] = " / ".join(([labels[f]] if f in labels else []) + names)
    return dict(sorted(labels.items()))


def decoded_review(ffmpeg, video, shot, sheet_path, deadline):
    """Decode the actual delivery file with the selected, supervised FFmpeg executable."""

    def read(filters, size, pixel_format, count, limit):
        result = run_capture(
            [
                ffmpeg,
                "-nostdin",
                "-v",
                "error",
                "-xerror",
                "-threads",
                "1",
                "-filter_threads",
                "1",
                "-i",
                str(video),
                "-map",
                "0:v:0",
                "-vf",
                filters,
                "-fps_mode",
                "passthrough",
                "-frames:v",
                str(limit),
                "-c:v",
                "rawvideo",
                "-threads",
                "1",
                "-pix_fmt",
                pixel_format,
                "-f",
                "rawvideo",
                "pipe:1",
            ],
            timeout=deadline - time.monotonic(),
        )
        if result.returncode or result.survivors:
            detail = result.stderr.decode(errors="replace")[-500:]
            raise RuntimeError(f"Visual review decode failed: {detail}")
        channels = 1 if pixel_format == "gray" else 3
        if len(result.stdout) != count * size[0] * size[1] * channels:
            raise ValueError(f"Visual review expected {count} {pixel_format} frames")
        return result.stdout

    width, height = LUMA_SIZE
    # One extra frame exposes a longer-than-declared delivery without unbounded capture.
    data = read(f"scale={width}:{height}:flags=area", LUMA_SIZE, "gray", len(shot), len(shot) + 1)
    gray = np.frombuffer(data, dtype=np.uint8).reshape(len(shot), height, width)
    notes = picture_notes(gray, shot.start)
    labels = review_frames(shot, notes)
    select = "+".join(f"eq(n\\,{f - shot.start})" for f in labels)
    w, h = CELL_SIZE
    raw = read(
        f"select={select},scale={w}:{h}:flags=area", CELL_SIZE, "rgb24", len(labels), len(labels)
    )
    pixels = np.frombuffer(raw, dtype=np.uint8).reshape(len(labels), h, w, 3)
    columns = min(len(labels), 3)
    row_height = h + 28
    sheet = Image.new(
        "RGB", (columns * w, ((len(labels) + columns - 1) // columns) * row_height), "#20272b"
    )
    pen = ImageDraw.Draw(sheet)
    for index, (f, label) in enumerate(labels.items()):
        x = index % columns * w
        y = index // columns * row_height
        sheet.paste(Image.fromarray(pixels[index]), (x, y))
        pen.text((x + 6, y + h + 6), f"{f:03}   {label}", fill="#fff3dc")
    sheet.save(sheet_path, format="WEBP", quality=84)
    return {
        "schema_version": 1,
        "source_frame_range": [shot.start, shot.stop],
        "fps": FPS,
        "decoded_frames": len(gray),
        "analysis_size": list(LUMA_SIZE),
        "findings": notes,
        "sheet": sheet_path.name,
        "sheet_frames": [{"source_frame": f, "label": title} for f, title in labels.items()],
    }
