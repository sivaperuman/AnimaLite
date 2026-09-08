"""Tiny end-to-end fixture render: encode, decode and validate the real output."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from animalite.contracts.enums import EvidenceStatus, JobState
from animalite.contracts.media import P_L_FINAL_OUTPUT, PREVIEW_OUTPUT
from animalite.contracts.results import DecodeProbe
from animalite.fixtures.generator import FIXTURE_CLIPS, generate_clip
from animalite.media.probe import probe_output, validate_output
from tests.conftest import make_request

pytestmark = [pytest.mark.media, pytest.mark.slow]


def test_the_fixture_renders_a_valid_six_second_640x360_clip(service, fixture_anchors):
    record = service.render_blocking(make_request(fixture_anchors))

    assert record.state is JobState.SUCCEEDED, record.failure
    assert record.output is not None
    probe = record.output.probe

    assert (probe.width, probe.height) == (640, 360)
    assert probe.codec == "h264"
    assert probe.pixel_format == "yuv420p"
    assert probe.counted_frames == 144
    assert probe.avg_frame_rate == "24/1"
    assert probe.duration_seconds == pytest.approx(6.0, abs=1e-3)
    assert probe.size_bytes > 0

    counts = record.output.frame_accounting
    assert counts.animation_frame_count == 72
    assert counts.delivery_frame_count == 144
    assert counts.source_frame_count == 2
    assert counts.synthesized_frame_count == 70
    assert counts.duplicated_frame_count == 72

    # The output exists, is published under output/, and is content-hashed.
    published = Path(record.output.path)
    assert published.is_file()
    assert published.parent.name == "output"
    assert record.output.content_hash.startswith("sha256:")

    # And it is unambiguously labelled as non-qualifying.
    assert record.output.is_qualifying_evidence is False
    assert "MR-018" in (record.output.non_qualifying_reason or "")


def test_the_preview_spec_renders_exactly_three_seconds_at_320x180(service, preview_anchors):
    record = service.render_blocking(make_request(preview_anchors, output=PREVIEW_OUTPUT))
    assert record.state is JobState.SUCCEEDED, record.failure
    assert record.output is not None
    probe = record.output.probe
    assert (probe.width, probe.height) == (320, 180)
    assert probe.counted_frames == 72
    assert probe.duration_seconds == pytest.approx(3.0, abs=1e-3)


def test_every_stage_is_recorded_inside_the_timing_boundary(service, fixture_anchors):
    record = service.render_blocking(make_request(fixture_anchors))
    stages = {s.stage.value for s in record.stages}
    expected = {
        "validate",
        "decode_anchors",
        "temporal_synthesis",
        "encode",
        "validate_output",
        "publish",
    }
    assert expected <= stages
    assert all(s.inside_timing_boundary for s in record.stages)
    assert record.wall_seconds is not None and record.wall_seconds > 0


def test_memory_evidence_is_measured_or_explicitly_unavailable(service, fixture_anchors):
    record = service.render_blocking(make_request(fixture_anchors))
    memory = record.memory
    if memory.status is EvidenceStatus.MEASURED:
        assert memory.peak_bytes is not None and memory.peak_bytes > 0
        assert memory.caveats, "a measured observation must disclose its caveats"
    else:
        assert memory.peak_bytes is None


def test_the_fixture_generator_is_reproducible(tmp_path, tools):
    clip = FIXTURE_CLIPS["fixture-three-anchor"]
    first = generate_clip(clip, tmp_path / "a", tools=tools)
    second = generate_clip(clip, tmp_path / "b", tools=tools)
    assert [a.asset.content_hash for a in first.anchors] == [
        a.asset.content_hash for a in second.anchors
    ]


def test_the_render_is_deterministic_for_identical_inputs(service, fixture_anchors):
    first = service.render_blocking(make_request(fixture_anchors, request_id="d1"))
    second = service.render_blocking(make_request(fixture_anchors, request_id="d2"))
    assert first.output is not None and second.output is not None
    assert first.output.content_hash == second.output.content_hash
    assert first.settings_digest == second.settings_digest


def test_a_truncated_output_file_fails_decode_validation(service, fixture_anchors, tools):
    record = service.render_blocking(make_request(fixture_anchors))
    assert record.output is not None
    published = Path(record.output.path)

    truncated = published.parent / "truncated.mp4"
    truncated.write_bytes(published.read_bytes()[: published.stat().st_size // 3])
    try:
        probe = probe_output(tools, truncated)
    except Exception:
        return  # a badly truncated file may not probe at all, which is also a rejection
    assert validate_output(probe, P_L_FINAL_OUTPUT), "a truncated file must not validate"


def test_validate_output_rejects_each_contract_violation():
    good = DecodeProbe(
        container_format="mov,mp4",
        codec="h264",
        profile="High",
        width=640,
        height=360,
        pixel_format="yuv420p",
        counted_frames=144,
        avg_frame_rate="24/1",
        duration_seconds=6.0,
        size_bytes=1234,
    )
    assert validate_output(good, P_L_FINAL_OUTPUT) == []

    cases: list[tuple[str, dict[str, object]]] = [
        ("geometry", {"width": 320}),
        ("pixel format", {"pixel_format": "yuv444p"}),
        ("delivery frames", {"counted_frames": 143}),
        ("frame rate", {"avg_frame_rate": "12/1"}),
        ("duration", {"duration_seconds": 5.9}),
        ("zero bytes", {"size_bytes": 0}),
    ]
    for label, update in cases:
        problems = validate_output(good.model_copy(update=update), P_L_FINAL_OUTPUT)
        assert problems, f"{label} violation was not detected"


def test_ffmpeg_is_invoked_with_an_argument_array_not_a_shell_string(tools, tmp_path):
    """A path containing shell metacharacters must be passed through safely."""
    from animalite.media.decode import decode_image_rgb24

    hostile_dir = tmp_path / "a dir; touch pwned"
    hostile_dir.mkdir()
    clip = FIXTURE_CLIPS["fixture-two-anchor"]
    anchors = generate_clip(clip, hostile_dir, tools=tools)
    frame = decode_image_rgb24(tools, Path(anchors.anchors[0].asset.path), width=64, height=36)
    assert frame.shape == (36, 64, 3)
    assert not (tmp_path / "pwned").exists()
    assert not Path("pwned").exists()


def test_the_encoder_command_pins_every_output_affecting_setting(tools):
    from animalite.media.encode import encoder_argv

    argv = encoder_argv(tools, P_L_FINAL_OUTPUT, Path("out.mp4"), threads=2)
    # Input-side flags come before "-i"; assert on the output side only.
    output_argv = argv[argv.index("-i") + 2 :]
    for flag, value in (
        ("-c:v", "libx264"),
        ("-profile:v", "high"),
        ("-level", "3.1"),
        ("-pix_fmt", "yuv420p"),
        ("-crf", "18"),
        ("-preset", "medium"),
        ("-colorspace", "bt709"),
        ("-color_range", "tv"),
        ("-threads", "2"),
    ):
        assert flag in output_argv, f"{flag} is not pinned on the output"
        assert output_argv[output_argv.index(flag) + 1] == value, f"{flag} is not {value}"
    assert "-vsync" in output_argv
    assert output_argv[output_argv.index("-vsync") + 1] == "passthrough"
    # Input geometry and rate are pinned too, so the encoder never guesses.
    input_argv = argv[: argv.index("-i")]
    assert input_argv[input_argv.index("-s") + 1] == "640x360"
    assert input_argv[input_argv.index("-r") + 1] == "24"
    assert input_argv[input_argv.index("-pix_fmt") + 1] == "rgb24"
    # Nothing is passed through a shell.
    assert not any(isinstance(a, str) and ";" in a for a in argv[:-1])


def test_the_published_clip_actually_plays_back_frame_by_frame(service, fixture_anchors, tools):
    """Decode every frame to raw video: a container that will not fully decode fails."""
    record = service.render_blocking(make_request(fixture_anchors))
    assert record.output is not None
    completed = subprocess.run(
        [
            tools.ffmpeg_path,
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
            "-i",
            record.output.path,
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode()[-500:]
    assert len(completed.stdout) == 144 * 640 * 360 * 3
