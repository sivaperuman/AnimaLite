"""Mix the dialogue, bus bell, footsteps and harbour ambience."""

import json
import wave

import numpy as np
from scipy.signal import butter, sosfilt


def mix_sound(p):
    sample_rate = 48000
    sample_count = 15 * sample_rate
    rng = np.random.default_rng(321)
    out = np.zeros((sample_count, 2))
    tt = np.arange(sample_count) / sample_rate

    def put(at, x, pan=0):
        i = round(at * sample_rate)
        x = x[: min(len(x), sample_count - i)]
        out[i : i + len(x), 0] += x * np.sqrt((1 - pan) / 2)
        out[i : i + len(x), 1] += x * np.sqrt((1 + pan) / 2)

    def band(n, lo, hi):
        return sosfilt(
            butter(2, [lo, hi], fs=sample_rate, btype="band", output="sos"), rng.normal(size=n)
        )

    put(0, 0.010 * band(sample_count, 180, 1350) * (0.7 + 0.30 * np.sin(tt * 1.1)), 0.18)

    def strike(at, pitch, amp, length, decay, pan):
        t = np.arange(int(sample_rate * length)) / sample_rate
        put(
            at,
            amp
            * np.exp(-t * decay)
            * np.minimum(1, t * 140)
            * (np.sin(2 * np.pi * pitch * t) + 0.27 * np.sin(2 * np.pi * pitch * 2.7 * t)),
            pan,
        )

    for at, fr in [(8.49, 739.99), (8.68, 987.77)]:
        strike(at, fr, 0.12, 0.53, 7, 0.38)
    for at in [14.03, 14.13]:
        strike(at, 470, 0.07, 0.13, 35, 0.24)
    for at, running in json.loads((p / "strikes.json").read_text()):
        t = np.arange(int(sample_rate * 0.115)) / sample_rate
        amp = 0.20 if running else 0.115
        snd = (
            np.exp(-t * 38)
            * np.minimum(1, t * 500)
            * (np.sin(2 * np.pi * (124 * t - 210 * t * t)) + band(len(t), 350, 1700) * 0.40)
        )
        put(at, amp * snd, -0.1)
    with wave.open(str(p / "milo.wav"), "rb") as f:
        x = np.frombuffer(f.readframes(f.getnframes()), dtype="<i2").astype(float) / 32768
    put(6.25, x * 0.88 / max(abs(x)), -0.03)
    out *= np.minimum(1, tt * 4)[:, None] * np.minimum(1, (15 - tt) * 4)[:, None]
    with wave.open(str(p / "mix.wav"), "wb") as f:
        f.setparams((2, 2, sample_rate, 0, "NONE", "PCM"))
        f.writeframes((np.clip(out, -1, 1) * 32767).astype("<i2").tobytes())
