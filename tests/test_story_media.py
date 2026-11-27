"""Check framing against decoded pixels and dialogue against the sample clock."""

import json
import wave
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from animalite.errors import ValidationRejected
from animalite.proc import run_capture
from animalite.story import Storyboard
from animalite.story_media import AUDIO_RATE, Camera, Dialogue, ffmpeg, frame_shot, mix_shot


def test_text_dialogue_needs_cast_and_shot_time():
    shot = {
        "action": "look",
        "seconds": 1,
        "poses": [{"frame": 0, "image": "a.png"}, {"frame": 11, "image": "b.png"}],
        "dialogue": [{"character": "Max", "text": "Hey!"}],
    }
    board = {"story": "look", "shots": [shot]}
    with pytest.raises(ValidationError, match="no voice assigned"):
        Storyboard.model_validate_json(json.dumps(board))
    encoded = json.loads(json.dumps(board))
    encoded["voices"] = {"Max": "rms"}
    encoded["shots"][0]["dialogue"][0]["start_ms"] = 1000
    with pytest.raises(ValidationError, match="start within"):
        Storyboard.model_validate(encoded)


@pytest.mark.media
def test_mix_preserves_silence_offsets_overlap_and_rejects_overrun(tmp_path, tools):
    line_file = tmp_path / "line.wav"
    with wave.open(str(line_file), "wb") as wav:
        wav.setparams((1, 2, AUDIO_RATE, 0, "NONE", ""))
        wav.writeframes(np.full(4800, 1000, dtype="<i2").tobytes())
    one = Dialogue(character="Max", audio=Path("line.wav"), start_ms=200)
    two = Dialogue(character="Milo", audio=Path("line.wav"), start_ms=250)
    dest = tmp_path / "mixed.wav"
    with wave.open(str(dest), "wb") as wav:
        wav.setparams((1, 2, AUDIO_RATE, 0, "NONE", ""))
        mix_shot(tools, tmp_path, tmp_path, 1, 1, [], {}, wav)
        saved = mix_shot(tools, tmp_path, tmp_path, 2, 1, [one, two], {}, wav)
        assert all(line.audio and (tmp_path / line.audio).exists() for line in saved)
        with pytest.raises(ValidationRejected, match="shot 3, Max"):
            mix_shot(
                tools, tmp_path, tmp_path, 3, 1, [one.model_copy(update={"start_ms": 950})], {}, wav
            )
    with wave.open(str(dest), "rb") as wav:
        data = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
    assert len(data) == 2 * AUDIO_RATE
    assert not data[: AUDIO_RATE + 9600].any()
    assert data[AUDIO_RATE + 10000] == 1000
    assert data[AUDIO_RATE + 12500] == 2000
    assert not data[AUDIO_RATE + 16800 :].any()


@pytest.mark.media
@pytest.mark.parametrize(("start", "end"), [(1, 2), (2, 1)])
def test_zoom_changes_subject_size_in_the_requested_direction(tmp_path, tools, start, end):
    source = tmp_path / "source.mp4"
    ffmpeg(
        tools.ffmpeg_path,
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=640x360:r=24:d=1,drawbox=x=280:y=140:w=80:h=80:color=white:t=fill",
            "-threads",
            "2",
            str(source),
        ],
    )
    movie = frame_shot(
        tools.ffmpeg_path, source, tmp_path / "zoom.mp4", Camera(zoom_start=start, zoom_end=end), 1
    )
    result = run_capture(
        [
            tools.ffmpeg_path,
            "-v",
            "error",
            "-i",
            str(movie),
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "-threads",
            "1",
            "-",
        ],
        timeout=20,
    )
    assert result.returncode == 0
    frames = np.frombuffer(result.stdout, dtype=np.uint8).reshape(24, 360, 640)
    for frame, scale in [(frames[0], start), (frames[-1], end)]:
        assert (frame[180] > 150).sum() == pytest.approx(80 * scale, abs=3)


@pytest.mark.media
@pytest.mark.slow
def test_spoken_story_renders_and_replays_without_synthesizing_again(
    tmp_path, tools, preview_anchors
):
    from animalite.contracts.admission import AdmissionPurpose
    from animalite.story import render_story

    filters = run_capture([tools.ffmpeg_path, "-filters"], timeout=10)
    if b" flite " not in filters.stdout:
        pytest.skip("optional Flite offline voices unavailable on this FFmpeg build")
    board = tmp_path / "input.json"
    artwork = preview_anchors.anchors[0].asset.path
    poses = [{"frame": 0, "image": artwork}, {"frame": 35, "image": artwork}]
    shot = {
        "action": "respond",
        "seconds": 3,
        "poses": poses,
        "camera": {"angle": "reverse view", "zoom_end": 1.25},
        "dialogue": [{"character": "Milo", "text": "My ticket.", "start_ms": 250}],
    }
    board.write_text(json.dumps({"story": "ticket", "voices": {"Milo": "awb"}, "shots": [shot]}))
    movie = render_story(
        board, tmp_path / "runs", "classical-warp-baseline", AdmissionPurpose.PRODUCTION
    )
    saved = json.loads((movie.parent / "storyboard.json").read_text())
    assert saved["shots"][0]["camera"]["angle"] == "reverse view"
    wav_path = movie.parent / saved["shots"][0]["dialogue"][0]["audio"]
    with wave.open(str(wav_path), "rb") as wav:
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
        assert np.abs(samples.astype(np.int32)).max() > 100
    saved["voices"] = {}
    replay = movie.parent / "replay.json"
    replay.write_text(json.dumps(saved))
    again = render_story(
        replay, tmp_path / "runs", "classical-warp-baseline", AdmissionPurpose.PRODUCTION
    )
    assert (again.parent / "dialogue.wav").read_bytes() == (
        movie.parent / "dialogue.wav"
    ).read_bytes()
