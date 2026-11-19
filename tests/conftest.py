"""Shared fixtures.

Media tests are marked ``media`` and report *pending* (skip with a clear reason)
when FFmpeg is unavailable, rather than passing vacuously. Handoff section 8: "A
hardware-dependent test must report not-run/pending when the host or model is
unavailable."
"""

from __future__ import annotations

from pathlib import Path

import pytest

from animalite.adapters.registry import default_registry
from animalite.contracts.assets import AnchorSet, AssetRef, InputAnchor
from animalite.contracts.base import sha256_file
from animalite.contracts.job import RenderRequest
from animalite.contracts.media import P_L_FINAL_OUTPUT, OutputSpec
from animalite.contracts.shot import ShotIntent
from animalite.core.service import LocalExecutionService
from animalite.fixtures.generator import FIXTURE_CLIPS, generate_clip
from animalite.media.ffmpeg import FFmpegTools

_TOOLS = FFmpegTools.discover()


def require_media() -> None:
    """Skip with an explicit pending reason when FFmpeg is not installed."""
    if not _TOOLS.available:
        pytest.skip(f"PENDING (not run): FFmpeg tooling unavailable: {_TOOLS.unavailable_reason}")


@pytest.fixture(scope="session")
def tools() -> FFmpegTools:
    require_media()
    return _TOOLS


@pytest.fixture(scope="session")
def fixture_anchors(tmp_path_factory: pytest.TempPathFactory) -> AnchorSet:
    """Two-anchor 640x360 fixture anchors, generated once per test session."""
    require_media()
    out = tmp_path_factory.mktemp("fixture-anchors")
    return generate_clip(FIXTURE_CLIPS["fixture-two-anchor"], out, tools=_TOOLS)


@pytest.fixture(scope="session")
def preview_anchors(tmp_path_factory: pytest.TempPathFactory) -> AnchorSet:
    """Preview-shaped anchors: 36-frame animation stream, endpoints at 0 and 35."""
    require_media()
    out = tmp_path_factory.mktemp("preview-anchors")
    return generate_clip(FIXTURE_CLIPS["fixture-preview"], out, width=320, height=180, tools=_TOOLS)


@pytest.fixture()
def service(tmp_path: Path) -> LocalExecutionService:
    return LocalExecutionService(tmp_path / "ws", registry=default_registry(), tools=_TOOLS)


def make_request(
    anchors: AnchorSet,
    *,
    output: OutputSpec = P_L_FINAL_OUTPUT,
    profile_id: str = "fixture-synthetic",
    request_id: str = "test-request",
    timeout_seconds: float = 300.0,
    controls: dict[str, float | int | str | bool] | None = None,
    parent_attempt_id: str | None = None,
) -> RenderRequest:
    return RenderRequest(
        request_id=request_id,
        shot=ShotIntent(
            shot_code="TEST-SHOT", target_duration_seconds=float(output.duration_seconds)
        ),
        anchors=anchors,
        engine_profile_id=profile_id,
        output=output,
        controls=controls or {},
        timeout_seconds=timeout_seconds,
        parent_attempt_id=parent_attempt_id,
    )


def synthetic_anchor(
    tmp_path: Path,
    *,
    animation_index: int,
    width: int = 640,
    height: int = 360,
    approved: bool = True,
    anchor_id: str | None = None,
    payload: bytes | None = None,
) -> InputAnchor:
    """A cheap on-disk anchor for tests that never decode it."""
    path = tmp_path / f"anchor-{animation_index}-{anchor_id or 'x'}.png"
    path.write_bytes(payload if payload is not None else f"anchor-{animation_index}".encode())
    return InputAnchor(
        anchor_id=anchor_id or f"a{animation_index}",
        animation_index=animation_index,
        asset=AssetRef(
            path=str(path), content_hash=sha256_file(str(path)), size_bytes=path.stat().st_size
        ),
        width=width,
        height=height,
        approved=approved,
    )
