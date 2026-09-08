"""RIFE/ncnn adapter: runtime verification, timestep safety and learned synthesis.

Tests that need the pinned runtime report **pending** when it is absent, rather
than passing vacuously (handoff section 8). Tests that only need the contracts
run everywhere, including in CI, which never downloads weights.
"""

from __future__ import annotations

import numpy as np
import pytest

from animalite.adapters.rife_ncnn import RIFE_PROFILE, RifeNcnnAdapter
from animalite.adapters.rife_runtime import PINNED_MODELS, RIFE_RELEASE, RifeRuntime
from animalite.contracts.assets import AnchorSet
from animalite.contracts.enums import EngineClass, EvidenceStatus, JobState
from animalite.contracts.media import P_L_FINAL_OUTPUT
from animalite.errors import CodeVAL
from tests.conftest import make_request, synthetic_anchor

RUNTIME = RifeRuntime.discover()
RUNTIME_VERIFICATION = RUNTIME.verify("rife-v4.6")


def require_runtime() -> None:
    if not RUNTIME_VERIFICATION.usable:
        pytest.skip(
            "PENDING (not run): pinned RIFE runtime unavailable or unverified: "
            + "; ".join(RUNTIME_VERIFICATION.problems)
        )


def _anchors(tmp_path, first=0, last=71):
    return AnchorSet(
        anchors=[
            synthetic_anchor(tmp_path, animation_index=first, anchor_id="s"),
            synthetic_anchor(tmp_path, animation_index=last, anchor_id="e"),
        ]
    )


# --- contract-level: run everywhere ------------------------------------------


def test_the_profile_declares_a_learned_component_and_is_eligible():
    assert RIFE_PROFILE.engine_class is EngineClass.ML_ASSISTED
    assert RIFE_PROFILE.learned_temporal_participation is True
    assert RIFE_PROFILE.qualification_eligible is True
    assert RIFE_PROFILE.non_qualifying_reason is None
    assert RIFE_PROFILE.cpu_only_guaranteed is True


def test_every_declared_artifact_is_hash_pinned():
    """Handoff rule 7: verify the approved binary and weight hashes before use."""
    artifacts = [*RIFE_PROFILE.weights, *RIFE_PROFILE.binaries]
    assert artifacts, "the profile must declare its binary and weights"
    for artifact in artifacts:
        assert artifact.content_hash is not None, artifact.identifier
        assert artifact.content_hash.startswith("sha256:")
        assert len(artifact.content_hash) == len("sha256:") + 64
        assert artifact.source_url
        assert artifact.license_id


def test_the_licence_position_is_recorded_as_unresolved_not_asserted_clear():
    """CR-024: pending/unknown evidence maps to unresolved / not use-eligible."""
    evaluation = RIFE_PROFILE.license_evaluation
    assert evaluation is not None
    assert evaluation.use_eligible is False
    assert evaluation.policy_state == "pending"
    assert evaluation.eligibility_block_kind == "resolvable"


def test_an_unresolved_licence_warns_but_does_not_block_development(tmp_path):
    issues = RifeNcnnAdapter().validate(RIFE_PROFILE, _anchors(tmp_path), P_L_FINAL_OUTPUT, {})
    licence = [i for i in issues if i.code == CodeVAL.LICENCE_NOT_CLEARED]
    assert len(licence) == 1
    assert licence[0].severity.value == "warning"
    assert "C-04" in licence[0].remediation


def test_a_midpoint_only_model_is_rejected_for_arbitrary_timesteps(tmp_path):
    """The core safety rule: rife-anime returns a wrong frame, not an error.

    Measured: given t=0.25 / 0.50 / 0.75 it produced centroids 170.4 / 158.9 /
    158.9 -- non-monotonic, i.e. the subject moved backwards. So the
    combination is refused rather than trusted.
    """
    issues = RifeNcnnAdapter().validate(
        RIFE_PROFILE, _anchors(tmp_path), P_L_FINAL_OUTPUT, {"model": "rife-anime"}
    )
    codes = [i.code for i in issues]
    assert CodeVAL.RUNTIME_TIMESTEP_UNSUPPORTED in codes
    issue = next(i for i in issues if i.code == CodeVAL.RUNTIME_TIMESTEP_UNSUPPORTED)
    assert "midpoint-only" in issue.message
    assert "rife-v4.6" in issue.remediation


def test_a_midpoint_only_model_is_accepted_when_every_timestep_is_one_half(tmp_path):
    """The rule is about the timesteps actually needed, not the model alone."""
    from animalite.contracts.media import OutputSpec

    # Three animation frames with anchors at 0 and 2 needs only t=0.5.
    output = OutputSpec(width=640, height=360, animation_frame_count=3)
    anchors = _anchors(tmp_path, first=0, last=2)
    issues = RifeNcnnAdapter().validate(RIFE_PROFILE, anchors, output, {"model": "rife-anime"})
    assert CodeVAL.RUNTIME_TIMESTEP_UNSUPPORTED not in [i.code for i in issues]


def test_an_unpinned_model_is_rejected(tmp_path):
    issues = RifeNcnnAdapter().validate(
        RIFE_PROFILE, _anchors(tmp_path), P_L_FINAL_OUTPUT, {"model": "rife-v9.9"}
    )
    assert CodeVAL.RUNTIME_MODEL_UNKNOWN in [i.code for i in issues]


def test_unsupported_controls_are_reported(tmp_path):
    issues = RifeNcnnAdapter().validate(
        RIFE_PROFILE, _anchors(tmp_path), P_L_FINAL_OUTPUT, {"guidance_scale": 7.5}
    )
    assert CodeVAL.CONTROL_UNSUPPORTED in [i.code for i in issues]


def test_a_missing_runtime_is_reported_as_an_actionable_error(tmp_path, monkeypatch):
    monkeypatch.setenv("ANIMALITE_RIFE_BIN", str(tmp_path / "absent"))
    monkeypatch.setenv("ANIMALITE_RIFE_MODELS", str(tmp_path / "absent"))
    issues = RifeNcnnAdapter(runtime=RifeRuntime.discover()).validate(
        RIFE_PROFILE, _anchors(tmp_path), P_L_FINAL_OUTPUT, {}
    )
    unverified = [i for i in issues if i.code == CodeVAL.RUNTIME_UNVERIFIED]
    assert unverified
    assert "animalite runtime" in unverified[0].remediation


def test_a_tampered_binary_fails_verification(tmp_path, monkeypatch):
    """A digest mismatch must make the runtime unusable, not merely warn."""
    fake = tmp_path / "rife-ncnn-vulkan"
    fake.write_bytes(b"not the pinned binary")
    monkeypatch.setenv("ANIMALITE_RIFE_BIN", str(fake))
    monkeypatch.setenv("ANIMALITE_RIFE_MODELS", str(tmp_path))
    (tmp_path / "rife-v4.6").mkdir()
    verification = RifeRuntime.discover().verify("rife-v4.6")
    assert verification.binary_present
    assert not verification.binary_verified
    assert not verification.usable
    assert any("digest mismatch" in p for p in verification.problems)


def test_the_release_pins_are_full_sha256_digests():
    for key in ("archive_sha256", "binary_sha256"):
        assert len(RIFE_RELEASE[key]) == 64
        assert all(c in "0123456789abcdef" for c in RIFE_RELEASE[key])
    for model in PINNED_MODELS.values():
        for digest in model.file_hashes.values():
            assert len(digest) == 64


def test_required_timesteps_are_uniform_between_anchors(tmp_path):
    """Frame k between anchors i and j must map to t=(k-i)/(j-i), exactly."""
    from animalite.contracts.media import OutputSpec

    anchors = _anchors(tmp_path, first=0, last=4)
    output = OutputSpec(width=640, height=360, animation_frame_count=5)
    steps = RifeNcnnAdapter._required_timesteps(anchors, output)
    assert steps == [0.25, 0.5, 0.75]


# --- runtime-dependent: pending without the pinned install --------------------


@pytest.mark.media
@pytest.mark.slow
def test_the_learned_model_synthesizes_motion_rather_than_cross_fading(tmp_path, tools):
    """MR-018 as a measurement, not a declaration.

    A cross-fade between two anchors leaves two half-opacity ghosts, so almost
    no pixel keeps the subject's exact colour. Real temporal synthesis moves the
    subject and preserves it as one solid object. This test would fail for the
    fixture adapter, which is the point.
    """
    require_runtime()
    from animalite.adapters.base import AdapterContext
    from animalite.fixtures.generator import FIXTURE_CLIPS, _render_anchor
    from animalite.media.image import write_png_rgb24

    clip = FIXTURE_CLIPS["fixture-two-anchor"]
    left = _render_anchor(clip, 0, 640, 360)
    right = _render_anchor(clip, 8, 640, 360)
    truth = _render_anchor(clip, 4, 640, 360)

    for index, frame in ((0, left), (8, right)):
        write_png_rgb24(tools, frame, tmp_path / f"a{index}.png")

    from animalite.contracts.media import OutputSpec

    output = OutputSpec(width=640, height=360, animation_frame_count=9)
    anchors = AnchorSet(
        anchors=[
            synthetic_anchor(tmp_path, animation_index=0, anchor_id="s"),
            synthetic_anchor(tmp_path, animation_index=8, anchor_id="e"),
        ]
    )
    context = AdapterContext(
        anchor_frames={0: left, 8: right},
        output=output,
        anchors=anchors,
        profile=RIFE_PROFILE,
        scratch_dir=tmp_path / "scratch",
    )
    frames = list(RifeNcnnAdapter().synthesize(context))
    assert len(frames) == 9

    midpoint = frames[4].astype(np.float32)
    blend = (left.astype(np.float32) + right.astype(np.float32)) / 2.0

    # The fixture's moving subject is palette entry 2, deterministic from the seed.
    palette = (np.random.default_rng(clip.seed).integers(40, 215, size=(4, 3)) & 0xFE).astype(
        np.float32
    )
    subject = palette[2]

    def solid_subject_pixels(image: np.ndarray) -> int:
        return int((np.abs(image - subject).sum(axis=2) < 18).sum())

    truth_solid = solid_subject_pixels(truth.astype(np.float32))
    rife_solid = solid_subject_pixels(midpoint)
    blend_solid = solid_subject_pixels(blend)

    # A cross-fade retains far fewer solid-subject pixels than the true frame.
    assert blend_solid < truth_solid * 0.75, (
        f"the blend baseline is not behaving as expected: {blend_solid} vs {truth_solid}"
    )
    # Learned synthesis keeps the subject solid, close to ground truth.
    assert rife_solid > truth_solid * 0.9, (
        f"RIFE produced {rife_solid} solid-subject pixels vs ground truth "
        f"{truth_solid}; it is not synthesizing a coherent moving subject"
    )
    # And it is materially closer to ground truth than the blend is.
    rife_error = float(np.abs(midpoint - truth.astype(np.float32)).mean())
    blend_error = float(np.abs(blend - truth.astype(np.float32)).mean())
    assert rife_error < blend_error / 2.0, (
        f"RIFE MAE {rife_error:.3f} is not materially better than the "
        f"cross-fade MAE {blend_error:.3f}"
    )


@pytest.mark.media
@pytest.mark.slow
def test_anchors_are_reproduced_exactly_and_device_evidence_is_measured(tmp_path, tools):
    """Approved frames must not be round-tripped through the model (C-05)."""
    require_runtime()
    from animalite.adapters.base import AdapterContext
    from animalite.contracts.media import OutputSpec
    from animalite.fixtures.generator import FIXTURE_CLIPS, _render_anchor

    clip = FIXTURE_CLIPS["fixture-two-anchor"]
    left, right = _render_anchor(clip, 0, 640, 360), _render_anchor(clip, 4, 640, 360)
    output = OutputSpec(width=640, height=360, animation_frame_count=5)
    anchors = AnchorSet(
        anchors=[
            synthetic_anchor(tmp_path, animation_index=0, anchor_id="s"),
            synthetic_anchor(tmp_path, animation_index=4, anchor_id="e"),
        ]
    )
    context = AdapterContext(
        anchor_frames={0: left, 4: right},
        output=output,
        anchors=anchors,
        profile=RIFE_PROFILE,
        scratch_dir=tmp_path / "scratch",
    )
    frames = list(RifeNcnnAdapter().synthesize(context))
    assert np.array_equal(frames[0], left), "the first anchor was not reproduced exactly"
    assert np.array_equal(frames[4], right), "the last anchor was not reproduced exactly"

    evidence = context.device_evidence
    assert evidence is not None
    assert evidence.inference_device_status is EvidenceStatus.MEASURED
    assert evidence.inference_device == "cpu"
    assert evidence.hardware_acceleration_requested is False
    assert any("-g -1" in note for note in evidence.notes)
    assert any("invocations=3" in note for note in context.notes), context.notes


@pytest.mark.media
@pytest.mark.slow
def test_end_to_end_learned_render_is_labelled_honestly(tmp_path, fixture_anchors):
    """A learned render is still not qualification evidence, for the right reason."""
    require_runtime()
    from animalite.adapters.registry import default_registry
    from animalite.core.service import LocalExecutionService

    service = LocalExecutionService(tmp_path / "ws", registry=default_registry())
    record = service.render_blocking(
        make_request(fixture_anchors, profile_id="rife-ncnn-v4.6-cpu", timeout_seconds=900)
    )
    assert record.state is JobState.SUCCEEDED, record.failure
    assert record.output is not None

    probe = record.output.probe
    assert probe.counted_frames == 144
    assert probe.duration_seconds == pytest.approx(6.0, abs=1e-3)
    counts = record.output.frame_accounting
    assert (counts.source_frame_count, counts.synthesized_frame_count) == (2, 70)

    # Eligible profile, but the artifact is still not evidence -- and the reason
    # must NOT be the fixture's "no learned model is integrated".
    assert record.output.is_qualifying_evidence is False
    reason = record.output.non_qualifying_reason or ""
    assert "qualification-eligible" in reason
    assert "AT-055" in reason
    assert "no learned temporal model is integrated" not in reason

    # Model time must be attributed to synthesis, not to the encoder.
    stages = {s.stage.value: s.wall_seconds for s in record.stages}
    assert stages["temporal_synthesis"] > stages["encode"], (
        f"model inference was misattributed: synthesis={stages['temporal_synthesis']}s "
        f"encode={stages['encode']}s"
    )
