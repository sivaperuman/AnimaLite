"""Render the 15-second Milo and Max harbour demo with AnimaLite speech cues."""

import argparse
import json
import shutil
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from sound import mix_sound

from animalite.performance import speech_cues
from animalite.proc import run_capture
from animalite.story_media import Dialogue, ffmpeg


def render(output: Path, drawing_python: str) -> None:
    binary = shutil.which("ffmpeg")
    if not binary:
        raise RuntimeError("Install FFmpeg with the flite and libx264 filters/codecs.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="harbour-", dir=output.parent) as tmp:
        work = Path(tmp).resolve()
        (work / "line.txt").write_text("Max! You forgot your lunch!\n", encoding="utf-8")
        ffmpeg(
            binary,
            [
                "-f",
                "lavfi",
                "-i",
                "flite=voice=awb:textfile=line.txt",
                "-af",
                "highpass=f=85,volume=1.28",
                "-ar",
                "48000",
                "-ac",
                "1",
                "milo.wav",
            ],
            cwd=work,
        )
        line = Dialogue(character="Milo", audio=Path("milo.wav"), start_ms=6250)
        cues = speech_cues(work, [line], 15)["Milo"]
        (work / "mouth.json").write_text(json.dumps(cues))
        job = run_capture(
            [drawing_python, str(Path(__file__).with_name("draw.py").resolve()), str(work)],
            timeout=300,
            cwd=work,
        )
        if job.returncode or job.survivors:
            raise RuntimeError(f"Harbour drawing failed: {job.stderr.decode(errors='replace')}")
        mix_sound(work)
        ffmpeg(
            binary,
            [
                "-framerate",
                "60",
                "-i",
                "frame-%04d.png",
                "-i",
                "mix.wav",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "libx264",
                "-crf",
                "17",
                "-preset",
                "veryfast",
                "-threads",
                "3",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "144k",
                "-movflags",
                "+faststart",
                "finished.mp4",
            ],
            cwd=work,
        )
        (work / "finished.mp4").replace(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="destination MP4")
    parser.add_argument("--drawing-python", default=sys.executable, help="Python with Pycairo")
    args = parser.parse_args()
    render(args.output, args.drawing_python)
