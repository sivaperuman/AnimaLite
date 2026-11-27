"""Audio-reactive character channels, vector compositing and actual orbital motion."""

import json
import shutil
import wave
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from animalite.contracts.admission import AdmissionPurpose
from animalite.performance import REST, Mouth, draw_mouths, speech_cues
from animalite.proc import run_capture
from animalite.story import StoryShot, render_story
from animalite.story_media import AUDIO_RATE, Dialogue, ffmpeg


def record(path, frequency, ticks):
    t = np.arange(ticks * AUDIO_RATE // 24) / AUDIO_RATE
    with wave.open(str(path), "wb") as out:
        out.setparams((1, 2, AUDIO_RATE, 0, "NONE", "PCM"))
        out.writeframes((8000 * np.sin(2 * np.pi * frequency * t)).astype("<i2").tobytes())


def test_cues_follow_offsets_silence_overlap_and_spectral_shape(tmp_path):
    record(tmp_path / "low.wav", 400, 6)
    record(tmp_path / "high.wav", 3600, 6)
    tracks = speech_cues(
        tmp_path,
        [
            Dialogue(character="Milo", audio=Path("low.wav"), start_ms=250),
            Dialogue(character="Max", audio=Path("high.wav"), start_ms=375),
        ],
        1,
    )
    a, b = tracks["Milo"], tracks["Max"]
    assert len(a) == len(b) == 24
    assert a[:6] == [REST] * 6 and a[12:] == [REST] * 12
    assert b[:9] == [REST] * 9 and b[15:] == [REST] * 9
    assert a[10][0] > 0 and b[10][0] > 0
    assert a[10][1] > a[10][2] and b[10][2] > b[10][1]


def test_stage_source_must_be_unambiguous():
    with pytest.raises(ValidationError, match="choose either"):
        StoryShot.model_validate(
            {
                "seconds": 1,
                "action": "orbit",
                "stage": {"actors": {"Milo": {}}, "model": "milo.glb"},
            }
        )
    with pytest.raises(ValidationError, match="omit poses"):
        StoryShot.model_validate(
            {
                "seconds": 1,
                "action": "orbit",
                "stage": {"actors": {"Milo": {}}},
                "poses": [{"frame": 0, "image": "p.png"}],
            }
        )


def gray_frames(binary, movie):
    result = run_capture(
        [
            binary,
            "-v",
            "error",
            "-i",
            str(movie),
            "-an",
            "-pix_fmt",
            "gray",
            "-f",
            "rawvideo",
            "-threads",
            "1",
            "-",
        ],
        timeout=30,
    )
    assert result.returncode == 0
    return np.frombuffer(result.stdout, dtype=np.uint8).reshape(-1, 360, 640)


@pytest.mark.media
def test_drawn_mouth_moves_only_during_speakers_line(tmp_path, tools):
    filters = run_capture([tools.ffmpeg_path, "-filters"], timeout=10)
    if b" ass " not in filters.stdout:
        pytest.skip("libass required for vector mouth")
    source = tmp_path / "white.mp4"
    ffmpeg(
        tools.ffmpeg_path,
        ["-f", "lavfi", "-i", "color=white:s=640x360:d=1:r=24", "-threads", "1", str(source)],
    )
    cues = {"Milo": [REST] * 6 + [(1, 0, 0)] * 9 + [REST] * 9}
    video = draw_mouths(
        tools.ffmpeg_path,
        source,
        tmp_path,
        1,
        1,
        {"Milo": Mouth(at=(0.25, 0.5)), "Max": Mouth(at=(0.75, 0.5))},
        cues,
    )
    frames = gray_frames(tools.ffmpeg_path, video)
    assert len(frames) == 24
    for tick in [0, 5, 6, 14, 15, 23]:
        milo = (frames[tick, :, 130:190] < 100).sum()
        max_pixels = (frames[tick, :, 450:510] < 100).sum()
        assert max_pixels > 0
        assert (milo > max_pixels * 2) == (6 <= tick < 15)


@pytest.mark.slow
@pytest.mark.media
def test_full_turn_with_speech_is_decodable_and_returns_to_initial_view(tmp_path, tools):
    if not shutil.which("blender"):
        pytest.skip("optional Blender renderer unavailable")
    record(tmp_path / "test.wav", 550, 3)
    board = {
        "story": "orbit",
        "shots": [
            {
                "action": "look around",
                "seconds": 1,
                "stage": {
                    "actors": {"Milo": {"x": -0.55}, "Max": {"x": 0.55, "shirt": "#993377"}},
                    "orbit": {"yaw": [0, 360], "radius": 5.2},
                },
                "dialogue": [{"character": "Milo", "audio": "test.wav", "start_ms": 125}],
            }
        ],
    }
    manifest = tmp_path / "input.json"
    manifest.write_text(json.dumps(board))
    movie = render_story(
        manifest, tmp_path / "renders", "classical-warp-baseline", AdmissionPurpose.PRODUCTION
    )
    frames = gray_frames(tools.ffmpeg_path, movie).astype(float)
    assert len(frames) == 24
    delta = np.abs(frames - frames[0]).mean(axis=(1, 2))
    assert delta[-1] < 1.0
    assert delta[6] > 3 and delta[12] > 2
    saved = json.loads((movie.parent / "storyboard.json").read_text())["shots"][0]
    assert saved["stage"]["orbit"]["yaw"] == [0, 360]
    assert (movie.parent / saved["dialogue"][0]["audio"]).is_file()
