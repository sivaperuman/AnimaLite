"""CLI surface: help, machine-readable output and mandatory explicit profile."""

from __future__ import annotations

import json

import pytest

from animalite.cli import build_parser, main
from animalite.media.ffmpeg import FFmpegTools

TOOLS = FFmpegTools.discover()


def test_help_lists_the_documented_operations(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])
    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    for command in ("doctor", "validate", "render", "benchmark", "fixtures", "profiles"):
        assert command in out
    # argparse rewraps the description, so compare on normalized whitespace.
    normalized = " ".join(out.split())
    assert "No learned temporal model is integrated" in normalized
    assert "no section 12.0 target has been measured or met" in normalized


def test_doctor_json_is_parseable_and_declares_no_approval(capsys):
    code = main(["doctor", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["approval"]["approved"] is False
    assert payload["schema_version"].startswith("animalite.contracts/")
    assert payload["memory_measurement_status"] in {"measured", "unavailable", "pending"}
    if payload["memory_measurement_status"] != "measured":
        assert payload["memory_measurement_method"] == "none"
    assert code in {0, 3}


def test_doctor_reports_unavailable_tooling_with_a_distinct_exit_code(capsys, monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent")
    monkeypatch.setenv("ANIMALITE_FFMPEG", "/nonexistent/ffmpeg")
    monkeypatch.setenv("ANIMALITE_FFPROBE", "/nonexistent/ffprobe")
    assert main(["doctor", "--json"]) == 3
    payload = json.loads(capsys.readouterr().out)
    assert all(not t["available"] for t in payload["tools"])
    assert any("unavailable" in w for w in payload["warnings"])


def test_render_requires_an_explicit_profile():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["render", "--anchors", "anchors.json"])


def test_profiles_reports_the_fixture_as_non_qualifying(capsys):
    assert main(["profiles", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    fixture = next(r for r in rows if r["profile_id"] == "fixture-synthetic")
    assert fixture["qualification_eligible"] is False
    assert fixture["learned_temporal_participation"] is False
    assert "MR-018" in fixture["non_qualifying_reason"]
    # No learned profile is registered yet, so none can claim eligibility.
    assert not any(r["qualification_eligible"] for r in rows)


def test_capabilities_reports_the_non_qualifying_label(capsys):
    assert main(["capabilities", "--profile", "fixture-synthetic"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["qualification_eligible"] is False
    assert payload["supported_controls"] == ["ease", "drift_pixels"]
    assert payload["cpu_only_guaranteed"] is True


@pytest.mark.media
def test_validate_exits_non_zero_and_explains_an_invalid_request(tmp_path, capsys):
    if not TOOLS.available:
        pytest.skip("PENDING (not run): FFmpeg tooling unavailable")
    from animalite.fixtures.generator import FIXTURE_CLIPS, generate_clip, write_anchor_set

    anchors = generate_clip(FIXTURE_CLIPS["fixture-two-anchor"], tmp_path, tools=TOOLS)
    manifest = write_anchor_set(anchors, tmp_path / "anchors.json")
    code = main(
        [
            "validate",
            "--profile",
            "fixture-synthetic",
            "--anchors",
            str(manifest),
            "--control",
            "nonexistent=1",
            "--json",
        ]
    )
    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is False
    codes = [i["code"] for i in payload["issues"]]
    assert "VAL-CONTROL-UNSUPPORTED" in codes
    assert all(i["remediation"] for i in payload["issues"] if i["severity"] == "error")


@pytest.mark.media
@pytest.mark.slow
def test_render_writes_a_labelled_manifest(tmp_path, capsys):
    if not TOOLS.available:
        pytest.skip("PENDING (not run): FFmpeg tooling unavailable")
    from animalite.fixtures.generator import FIXTURE_CLIPS, generate_clip, write_anchor_set

    anchors = generate_clip(FIXTURE_CLIPS["fixture-two-anchor"], tmp_path, tools=TOOLS)
    manifest = write_anchor_set(anchors, tmp_path / "anchors.json")
    code = main(
        [
            "render",
            "--profile",
            "fixture-synthetic",
            "--anchors",
            str(manifest),
            "--workspace",
            str(tmp_path / "ws"),
            "--json",
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    payload = json.loads(captured.out)
    assert payload["state"] == "succeeded"
    assert payload["output"]["is_qualifying_evidence"] is False
    assert payload["output"]["probe"]["counted_frames"] == 144
    # Diagnostics stay off stdout so the JSON stream is safe to pipe.
    assert "not evidence for MR-018" in captured.err
