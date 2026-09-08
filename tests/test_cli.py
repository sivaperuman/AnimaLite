"""CLI surface: help, machine-readable output and mandatory explicit profile."""

from __future__ import annotations

import json

import pytest

from animalite.cli import build_parser, main
from animalite.contracts.assets import AnchorSet
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
    """Rendering never selects an engine implicitly.

    `--profile` is no longer an argparse-level requirement, because an
    `--envelope` carries the resolved profile instead. The rule itself is
    unchanged and is enforced where the request is built, so this asserts the
    refusal rather than the argparse mechanics that used to produce it.
    """
    from animalite.cli import _request
    from animalite.errors import ValidationRejected

    parser = build_parser()
    args = parser.parse_args(["render", "--anchors", "anchors.json"])
    assert args.profile is None
    with pytest.raises(ValidationRejected, match="--profile is required"):
        _request(args)


def test_profiles_separates_learned_from_non_learned(capsys):
    assert main(["profiles", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)

    fixture = next(r for r in rows if r["profile_id"] == "fixture-synthetic")
    assert fixture["qualification_eligible"] is False
    assert fixture["learned_temporal_participation"] is False
    assert "MR-018" in fixture["non_qualifying_reason"]

    # Package B registers a learned profile. Eligibility and learned
    # participation must agree, in both directions, for every registered
    # profile -- the EngineProfile validator enforces this, and this asserts the
    # registry actually reflects it.
    for row in rows:
        if row["qualification_eligible"]:
            assert row["learned_temporal_participation"], row["profile_id"]
            assert row["non_qualifying_reason"] is None, row["profile_id"]
        else:
            assert row["non_qualifying_reason"], row["profile_id"]

    rife = next(r for r in rows if r["profile_id"] == "rife-ncnn-v4.6-cpu")
    assert rife["learned_temporal_participation"] is True
    assert rife["qualification_eligible"] is True


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


# --- R3 regression: the execution envelope carries and re-checks identity ----


def _envelope_payload(tmp_path, *, profile=None, digest=None, tools=None):
    from animalite.adapters.registry import default_registry
    from animalite.contracts.base import content_digest
    from animalite.contracts.job import ExecutionEnvelope
    from animalite.contracts.media import P_L_FINAL_OUTPUT
    from animalite.media.ffmpeg import FFmpegTools
    from tests.conftest import make_request, synthetic_anchor

    resolved = profile or default_registry().profile("fixture-synthetic")
    anchors = AnchorSet(
        anchors=[
            synthetic_anchor(tmp_path, animation_index=0, anchor_id="s"),
            synthetic_anchor(tmp_path, animation_index=71, anchor_id="e"),
        ]
    )
    envelope = ExecutionEnvelope(
        envelope_id="cli-envelope",
        request=make_request(anchors, output=P_L_FINAL_OUTPUT),
        profile=resolved,
        profile_digest=digest or content_digest(resolved),
        expected_tools=(tools or FFmpegTools.discover().with_content_hashes()).selection(),
    )
    path = tmp_path / "envelope.json"
    path.write_text(envelope.model_dump_json(indent=2), encoding="utf-8")
    return path, envelope


def test_an_envelope_supplies_the_profile_the_caller_resolved(tmp_path):
    """The envelope's profile replaces a same-id default rather than losing to it."""
    from animalite.adapters.registry import default_registry
    from animalite.cli import _registry, build_parser

    overridden = (
        default_registry()
        .profile("fixture-synthetic")
        .model_copy(update={"parameters": {"ease": "linear", "drift_pixels": 12.0}})
    )
    path, _ = _envelope_payload(tmp_path, profile=overridden)
    args = build_parser().parse_args(["render", "--envelope", str(path)])
    resolved = _registry(args).profile("fixture-synthetic")
    assert resolved.parameters == {"ease": "linear", "drift_pixels": 12.0}


def test_an_envelope_whose_digest_does_not_match_its_profile_is_refused(tmp_path):
    """A profile that no longer hashes to its declared identity must not execute."""
    from animalite.cli import _envelope, build_parser
    from animalite.errors import ValidationRejected

    path, _ = _envelope_payload(tmp_path, digest="sha256:" + "0" * 64)
    args = build_parser().parse_args(["render", "--envelope", str(path)])
    with pytest.raises(ValidationRejected, match="does not match its declared identity"):
        _envelope(args)


def test_an_envelope_cannot_introduce_an_adapter(tmp_path):
    """An envelope names an adapter key; it can never supply an implementation."""
    from animalite.adapters.registry import default_registry
    from animalite.cli import _registry, build_parser
    from animalite.errors import ProfileNotFoundError

    smuggled = (
        default_registry()
        .profile("fixture-synthetic")
        .model_copy(update={"adapter_key": "not-registered-anywhere"})
    )
    path, _ = _envelope_payload(tmp_path, profile=smuggled)
    args = build_parser().parse_args(["render", "--envelope", str(path)])
    with pytest.raises(ProfileNotFoundError, match="not-registered-anywhere"):
        _registry(args)
