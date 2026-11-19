"""Contact and timing regressions for the fixed S1 blocking (no renderer needed)."""

from itertools import pairwise
from math import isclose

import pytest
from performance import FRAMES, Chain, boot_pitch, pose


def test_stride_support_and_reach():
    for frame in range(FRAMES):
        milo, owner, _ = pose(frame)
        for actor in (milo, owner):
            for chain in actor.chains:
                joint = chain.joint()
                assert isclose(abs(joint - chain.root), chain.upper, abs_tol=1e-7)
                assert isclose(abs(chain.tip - joint), chain.lower, abs_tol=1e-7)
        far, near = milo.chains[:2]
        if frame <= 32 or frame >= 55:
            assert far.tip == complex(231 if frame <= 32 else 291, 305)
            assert abs(boot_pitch(frame, 32, 55)) < 1e-10
        if frame <= 55 or frame >= 80:
            assert near.tip == complex(251 if frame <= 55 else 311, 309)
            assert abs(boot_pitch(frame, 55, 80)) < 1e-10
    assert pose(44)[0].chains[0].tip.imag < 294
    assert pose(68)[0].chains[1].tip.imag < 298


def test_grip_transfer_and_visible_unfold():
    poses = [pose(f) for f in range(FRAMES)]
    for f, (milo, owner, paper) in enumerate(poses):
        if f <= 130:
            assert abs(milo.chains[2].tip - paper.right) < 1e-8
        if f <= 148:
            assert abs(milo.chains[3].tip - paper.left) < 1e-8
        if 130 <= f <= 150:
            assert abs(owner.chains[3].tip - paper.right) < 1e-8
        if f >= 143:
            assert abs(owner.chains[2].tip - paper.left) < 1e-8
        assert paper.owner == ("milo" if f < 143 else "owner")
    sheets = [p[2] for p in poses]
    for a, b in pairwise(sheets):
        assert abs(a.left - b.left) < 4 and abs(a.right - b.right) < 4
        assert 0 <= b.unfold - a.unfold < 0.05
    assert sheets[168].unfold == 0 and sheets[204].unfold == 1
    assert sheets[204].half_width > 1.7 * sheets[168].half_width


def test_invalid_targets_are_rejected():
    with pytest.raises(ValueError, match="Unreachable"):
        Chain(0j, 100j, 5, 5, 1).joint()
    with pytest.raises(ValueError, match="outside"):
        pose(FRAMES)
