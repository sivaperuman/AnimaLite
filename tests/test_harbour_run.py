"""Check the Harbour runner at the delivery cadence in world coordinates."""

import runpy
from itertools import groupby
from pathlib import Path

import pytest


def test_runner_takes_weight_on_the_planted_foot_and_rises_in_flight():
    pytest.importorskip("cairo", reason="Harbour demo requires Pycairo")
    draw = runpy.run_path(str(Path(__file__).resolve().parents[1] / "examples/harbour/draw.py"))
    # A steady stretch of the chase, with multiple complete left/right strides.
    samples = [(frame, draw["getpose"](frame / 60)) for frame in range(600, 781)]
    for side in (0, 1):
        for grounded, group in groupby(samples, key=lambda s: s[1]["ankles"][side][3]):
            stance = list(group)
            if grounded:
                assert len({pose["ankles"][side][:3] for _, pose in stance}) == 1
                assert draw["rootx"](stance[-1][0] / 60) > draw["rootx"](stance[0][0] / 60)

    phases = groupby(samples, key=lambda s: any(foot[3] for foot in s[1]["ankles"]))
    complete = [(supported, list(group)) for supported, group in phases][1:-1]
    assert len(complete) >= 12
    for supported, phase in complete:
        # Drawing Y increases downwards. Peak compression occurs over a
        # planted foot, and the highest hip position is inside the flight.
        extremum = max if supported else min
        frame, _ = extremum(phase, key=lambda s: s[1]["hip"][1])
        assert abs(frame - (phase[0][0] + phase[-1][0]) / 2) <= 1
