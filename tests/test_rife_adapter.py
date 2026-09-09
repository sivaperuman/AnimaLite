"""RIFE/ncnn adapter: admission, supervision, controls, evidence.

Three kinds of test live here, and the difference matters:

* **Contract tests** run everywhere, including CI. They need no runtime.
* **Stub-runtime tests** replace the executable with a tiny script that records
  its argv, stalls, or fails on demand. They exercise supervision, argv and
  evidence for real -- process groups, deadlines, cancellation -- without the
  431 MB release and without executing a model.
* **Model tests** need the pinned runtime *and* explicit opt-in *and* a recorded
  admission. Installing the runtime is not enough to start one: that is the
  point of B-R1, and a test that ran a model merely because it was present would
  contradict the thing it is testing.
"""

from __future__ import annotations

import os
import stat
import time
from pathlib import Path

import numpy as np
import pytest

from animalite.adapters.base import AdapterContext
from animalite.adapters.rife_ncnn import (
    RIFE_PROFILE,
    RifeNcnnAdapter,
    rife_job_spec,
)
from animalite.adapters.rife_runtime import (
    PINNED_MODELS,
    RIFE_RELEASE,
    RifeRuntime,
    RuntimeVerification,
)
from animalite.admission import evaluate_admission, profile_artifact_digests
from animalite.contracts.admission import AdmissionDecision, AdmissionPurpose
from animalite.contracts.assets import AnchorSet
from animalite.contracts.enums import EngineClass, EvidenceStatus, JobState
from animalite.contracts.media import P_L_FINAL_OUTPUT, OutputSpec
from animalite.errors import AdapterError, AdmissionDenied, CodeVAL, JobCancelled, JobTimeoutError
from tests.conftest import make_request, synthetic_anchor, write_admission

RUNTIME = RifeRuntime.discover()
RUNTIME_VERIFICATION = RUNTIME.verify("rife-v4.6")

#: Model tests need this set explicitly. Presence of the runtime is not consent
#: to execute it, and neither is a passing local install.
MODEL_TESTS_OPT_IN = "ANIMALITE_RUN_MODEL_TESTS"


def require_model_execution() -> None:
    """Skip as pending unless opt-in, runtime and admission are all present."""
    if os.environ.get(MODEL_TESTS_OPT_IN) != "1":
        pytest.skip(
            f"PENDING (not run): model execution tests require {MODEL_TESTS_OPT_IN}=1. "
            "An installed runtime is not on its own a reason to run a model."
        )
    if not RUNTIME_VERIFICATION.usable:
        pytest.skip(
            "PENDING (not run): pinned RIFE runtime unavailable or unverified: "
            + "; ".join(RUNTIME_VERIFICATION.problems)
        )
    outcome = evaluate_admission(RIFE_PROFILE, AdmissionPurpose.RESEARCH)
    if not outcome.admitted:
        pytest.skip(
            "PENDING (not run): no recorded execution admission for "
            f"{RIFE_PROFILE.profile_id}: {outcome.summary}"
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


def test_the_licence_warning_no_longer_claims_development_may_proceed(tmp_path):
    """B-R1. The old remediation said development and benchmarking may proceed.

    That sentence was the bug in prose form: the licence position warned, and
    nothing stopped the run. The warning still records the position -- what
    blocks execution is the separate admission check, and the remediation has to
    point at it rather than granting permission.
    """
    issues = RifeNcnnAdapter().validate(RIFE_PROFILE, _anchors(tmp_path), P_L_FINAL_OUTPUT, {})
    licence = [i for i in issues if i.code == CodeVAL.LICENCE_NOT_CLEARED]
    assert len(licence) == 1
    assert licence[0].severity.value == "warning"
    assert "may proceed" not in licence[0].remediation
    assert "VAL-ADMISSION" in licence[0].remediation


def test_a_midpoint_only_model_is_rejected_for_arbitrary_timesteps(tmp_path):
    """The combination is refused before anything runs.

    The reason recorded here used to be "rife-anime returns a plausible but
    temporally wrong frame rather than failing". The pinned wrapper contradicts
    that: it errors and exits -1 for a non-v4 model at a non-0.5 timestep, and
    the historical centroid measurement could not be reconstructed (DEC-0011).

    The rule stands on what is checkable: the architecture is midpoint-only, so
    the 72-frame contract cannot use it, and rejecting at validation turns a
    mid-render subprocess failure into an actionable message.
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


@pytest.mark.parametrize("value", ["false", "true", 1, 0, 7, 0.0])
def test_tta_spatial_must_be_a_real_boolean(tmp_path, value):
    """B-R3. ``"false"`` is a true string; ``7`` is a true int.

    A truthiness test turned both into "test-time augmentation on", which
    multiplies inference cost, while validation reported nothing at all.
    """
    issues = RifeNcnnAdapter().validate(
        RIFE_PROFILE, _anchors(tmp_path), P_L_FINAL_OUTPUT, {"tta_spatial": value}
    )
    invalid = [i for i in issues if i.code == CodeVAL.CONTROL_VALUE_INVALID]
    assert invalid, f"{value!r} was accepted as a boolean"
    assert invalid[0].field_path == "controls.tta_spatial"


@pytest.mark.parametrize("value", [True, False])
def test_a_real_boolean_tta_value_is_accepted(tmp_path, value):
    issues = RifeNcnnAdapter().validate(
        RIFE_PROFILE, _anchors(tmp_path), P_L_FINAL_OUTPUT, {"tta_spatial": value}
    )
    assert CodeVAL.CONTROL_VALUE_INVALID not in [i.code for i in issues]


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
    anchors = _anchors(tmp_path, first=0, last=4)
    output = OutputSpec(width=640, height=360, animation_frame_count=5)
    steps = RifeNcnnAdapter._required_timesteps(anchors, output)
    assert steps == [0.25, 0.5, 0.75]


def test_timestep_enumeration_does_not_raise_on_an_invalid_endpoint_request(tmp_path):
    """B-R3. Validation of a bad request must produce issues, not a traceback.

    Anchors at 0 and 4 against a 9-frame output leave frames 5..8 with no
    right-hand anchor. ``min()`` over an empty sequence turned a precise
    anchor-endpoint error into a ValueError raised from inside validation.
    """
    anchors = _anchors(tmp_path, first=0, last=4)
    output = OutputSpec(width=640, height=360, animation_frame_count=9)
    assert RifeNcnnAdapter._required_timesteps(anchors, output) == [0.25, 0.5, 0.75]
    issues = RifeNcnnAdapter().validate(RIFE_PROFILE, anchors, output, {"model": "rife-anime"})
    assert issues  # it still reports, it just does not explode


def test_the_declared_thread_allocation_fits_the_budget():
    """B-R5. ``-j 1:2:1`` named four runtime threads inside a four-thread total.

    The wrapper spawns load + proc + save threads in its own process, so the
    spec has to fit the whole budget rather than only the inference share.
    """
    load, proc, save = rife_job_spec(RIFE_PROFILE.thread_budget)
    budget = RIFE_PROFILE.thread_budget
    assert load + proc + save <= budget.total_threads
    assert proc <= budget.inference_threads
    assert proc >= 1


# --- stub runtime: supervision, argv and evidence without a model -------------


class _StubRuntime(RifeRuntime):
    """A runtime whose digests "verify" so supervision can be tested.

    Verification and admission are separate checks (B-R1), and this stubs only
    the first. A stub that also bypassed admission would make the admission
    tests below meaningless.
    """

    def verify(self, model_name: str) -> RuntimeVerification:
        return RuntimeVerification(
            binary_present=True, binary_verified=True, model_present=True, model_verified=True
        )

    def model_dir(self, model_name: str) -> Path | None:
        return self.models_root


def _stub_binary(tmp_path: Path, body: str, name: str = "stub-rife") -> Path:
    """Write an executable stub standing in for a native tool.

    ``name`` is not decoration: a test that stubs two tools at once needs two
    files, and a shared default silently overwrote the first with the second.
    """
    path = tmp_path / name
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IRUSR)
    return path


#: Records argv and the pinned thread environment, then produces the output by
#: copying the first input -- a real PNG, so the adapter's decode is exercised.
_COPYING_STUB = """
{
  echo "ARGV: $*"
  echo "OMP_NUM_THREADS=${OMP_NUM_THREADS-unset}"
} >> "$ANIMALITE_TEST_LOG"
IN=""
OUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    -0) IN="$2"; shift 2;;
    -o) OUT="$2"; shift 2;;
    *) shift;;
  esac
done
cp "$IN" "$OUT"
"""

#: Never returns and never writes an output file.
_STALLING_STUB = """
echo "started" >> "$ANIMALITE_TEST_LOG"
sleep 30
"""


def _stub_context(
    tmp_path: Path,
    tools,
    *,
    binary: Path,
    frame_count: int = 3,
    controls: dict[str, float | int | str | bool] | None = None,
    deadline: float | None = None,
    cancel=None,
    purpose: AdmissionPurpose = AdmissionPurpose.RESEARCH,
) -> tuple[AdapterContext, RifeNcnnAdapter]:
    left = np.zeros((180, 320, 3), dtype=np.uint8)
    left[40:80, 40:80] = 200
    right = np.zeros((180, 320, 3), dtype=np.uint8)
    right[40:80, 120:160] = 200
    last = frame_count - 1
    output = OutputSpec(width=320, height=180, animation_frame_count=frame_count)
    anchors = AnchorSet(
        anchors=[
            synthetic_anchor(tmp_path, animation_index=0, anchor_id="s", width=320, height=180),
            synthetic_anchor(tmp_path, animation_index=last, anchor_id="e", width=320, height=180),
        ]
    )
    models = tmp_path / "models" / "rife-v4.6"
    models.mkdir(parents=True, exist_ok=True)
    runtime = _StubRuntime(binary_path=binary, models_root=models.parent, root=tmp_path / "models")
    context = AdapterContext(
        anchor_frames={0: left, last: right},
        output=output,
        anchors=anchors,
        profile=RIFE_PROFILE,
        scratch_dir=tmp_path / "scratch",
        tools=tools,
        controls=controls or {},
        deadline=deadline if deadline is not None else time.monotonic() + 120.0,
        cancel=cancel,
        purpose=purpose,
    )
    return context, RifeNcnnAdapter(runtime=runtime)


@pytest.fixture()
def admitted(tmp_path, monkeypatch):
    """A synthetic approved record covering exactly this profile's artifacts."""
    directory = tmp_path / "admissions"
    write_admission(
        directory,
        profile_id=RIFE_PROFILE.profile_id,
        artifact_hashes=profile_artifact_digests(RIFE_PROFILE),
        purposes=[AdmissionPurpose.RESEARCH],
    )
    monkeypatch.setenv("ANIMALITE_ADMISSION_DIR", str(directory))
    return directory


# --- B-R1: admission blocks execution before anything is launched -------------


@pytest.mark.media
def test_a_missing_admission_record_blocks_execution_and_launches_nothing(
    tmp_path, tools, monkeypatch
):
    """The whole point: no record, no invocation. Not "no qualification"."""
    log = tmp_path / "log.txt"
    monkeypatch.setenv("ANIMALITE_TEST_LOG", str(log))
    binary = _stub_binary(tmp_path, _COPYING_STUB)
    context, adapter = _stub_context(tmp_path, tools, binary=binary)

    with pytest.raises(AdmissionDenied, match="not admitted"):
        list(adapter.synthesize(context))

    assert not log.exists(), "the runtime was executed despite admission being denied"
    assert not (tmp_path / "scratch" / "rife").exists(), (
        "a denied run wrote scratch files; it must be indistinguishable from never started"
    )


@pytest.mark.media
@pytest.mark.parametrize("decision", [AdmissionDecision.PENDING, AdmissionDecision.REJECTED])
def test_a_pending_or_rejected_record_blocks_execution(tmp_path, tools, monkeypatch, decision):
    log = tmp_path / "log.txt"
    monkeypatch.setenv("ANIMALITE_TEST_LOG", str(log))
    directory = tmp_path / "admissions"
    write_admission(
        directory,
        profile_id=RIFE_PROFILE.profile_id,
        artifact_hashes=profile_artifact_digests(RIFE_PROFILE),
        decision=decision,
    )
    monkeypatch.setenv("ANIMALITE_ADMISSION_DIR", str(directory))
    binary = _stub_binary(tmp_path, _COPYING_STUB)
    context, adapter = _stub_context(tmp_path, tools, binary=binary)

    with pytest.raises(AdmissionDenied, match=decision.value):
        list(adapter.synthesize(context))
    assert not log.exists()


@pytest.mark.media
def test_an_approved_record_admits_only_the_artifacts_it_names(tmp_path, tools, monkeypatch):
    """An approval covers the digests it lists, not the profile in general."""
    directory = tmp_path / "admissions"
    digests = profile_artifact_digests(RIFE_PROFILE)
    write_admission(
        directory,
        profile_id=RIFE_PROFILE.profile_id,
        artifact_hashes=digests[:-1],  # one weight file left out
    )
    monkeypatch.setenv("ANIMALITE_ADMISSION_DIR", str(directory))
    log = tmp_path / "log.txt"
    monkeypatch.setenv("ANIMALITE_TEST_LOG", str(log))
    context, adapter = _stub_context(tmp_path, tools, binary=_stub_binary(tmp_path, _COPYING_STUB))

    with pytest.raises(AdmissionDenied, match="artifacts_not_covered"):
        list(adapter.synthesize(context))
    assert not log.exists()


@pytest.mark.media
def test_an_approved_record_admits_only_the_purpose_it_permits(tmp_path, tools, monkeypatch):
    directory = tmp_path / "admissions"
    write_admission(
        directory,
        profile_id=RIFE_PROFILE.profile_id,
        artifact_hashes=profile_artifact_digests(RIFE_PROFILE),
        purposes=[AdmissionPurpose.RESEARCH],
    )
    monkeypatch.setenv("ANIMALITE_ADMISSION_DIR", str(directory))
    log = tmp_path / "log.txt"
    monkeypatch.setenv("ANIMALITE_TEST_LOG", str(log))
    context, adapter = _stub_context(
        tmp_path,
        tools,
        binary=_stub_binary(tmp_path, _COPYING_STUB),
        purpose=AdmissionPurpose.PRODUCTION,
    )

    with pytest.raises(AdmissionDenied, match="purpose_not_permitted"):
        list(adapter.synthesize(context))
    assert not log.exists()


@pytest.mark.media
def test_a_complete_admission_record_lets_synthesis_run(tmp_path, tools, admitted, monkeypatch):
    log = tmp_path / "log.txt"
    monkeypatch.setenv("ANIMALITE_TEST_LOG", str(log))
    context, adapter = _stub_context(tmp_path, tools, binary=_stub_binary(tmp_path, _COPYING_STUB))
    frames = list(adapter.synthesize(context))
    assert len(frames) == 3
    assert log.exists(), "the admitted run never invoked the runtime"


def test_validation_reports_a_missing_admission_as_an_error(tmp_path, fixture_anchors):
    """Render and benchmark both go through validation, so it must fail there."""
    from animalite.adapters.registry import default_registry
    from animalite.core.validation import validate_request

    report = validate_request(
        make_request(fixture_anchors, profile_id="rife-ncnn-v4.6-cpu"),
        default_registry(),
    )
    assert not report.valid
    assert CodeVAL.ADMISSION_NOT_RECORDED in report.error_codes
    issue = next(i for i in report.errors if i.code == CodeVAL.ADMISSION_NOT_RECORDED)
    assert "no development bypass" in issue.remediation


def test_the_repository_ships_no_approved_admission_record():
    """A checkout must not inherit an approval. The dossier is pending, always."""
    directory = Path(__file__).resolve().parents[1] / "docs" / "licensing" / "admissions"
    records = sorted(directory.glob("*.json"))
    assert records, "the pending dossier should be committed as the template to sign"
    for path in records:
        import json

        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["decision"] != AdmissionDecision.APPROVED.value, (
            f"{path.name} ships an approved admission; a repository cannot grant "
            "an operator's rights decision"
        )


# --- B-R2: every native call is bounded by the job deadline and cancel --------


@pytest.mark.media
def test_a_stalled_inference_is_stopped_by_the_job_deadline(tmp_path, tools, admitted, monkeypatch):
    """A 30 s stub against a 1 s job deadline must not run for 30 s.

    Before this, inference carried its own 600 s timeout: a 0.15 s job deadline
    was simply not consulted, and the encoder could not enforce it either
    because it was blocked pulling the generator.
    """
    log = tmp_path / "log.txt"
    monkeypatch.setenv("ANIMALITE_TEST_LOG", str(log))
    binary = _stub_binary(tmp_path, _STALLING_STUB)
    context, adapter = _stub_context(
        tmp_path, tools, binary=binary, deadline=time.monotonic() + 1.0
    )

    started = time.monotonic()
    with pytest.raises(JobTimeoutError) as caught:
        list(adapter.synthesize(context))
    elapsed = time.monotonic() - started

    assert elapsed < 12.0, f"the deadline was not enforced: returned after {elapsed:.2f}s"
    assert not caught.value.survivors, f"a process group survived: {caught.value.survivors}"
    assert log.exists(), "the stub never ran, so this proves nothing about supervision"


@pytest.mark.media
def test_an_expired_deadline_launches_nothing(tmp_path, tools, admitted, monkeypatch):
    """Expiry must stop the next launch, not grant it one more full allowance."""
    log = tmp_path / "log.txt"
    monkeypatch.setenv("ANIMALITE_TEST_LOG", str(log))
    binary = _stub_binary(tmp_path, _COPYING_STUB)
    context, adapter = _stub_context(
        tmp_path, tools, binary=binary, deadline=time.monotonic() - 0.001
    )

    with pytest.raises(JobTimeoutError):
        list(adapter.synthesize(context))
    assert not log.exists(), "an expired deadline still launched the runtime"


@pytest.mark.media
def test_cancellation_interrupts_a_stalled_inference(tmp_path, tools, admitted, monkeypatch):
    """Cancellation with a long deadline: the cancel is what stops it."""
    log = tmp_path / "log.txt"
    monkeypatch.setenv("ANIMALITE_TEST_LOG", str(log))
    cancel_at = time.monotonic() + 0.5
    binary = _stub_binary(tmp_path, _STALLING_STUB)
    context, adapter = _stub_context(
        tmp_path,
        tools,
        binary=binary,
        deadline=time.monotonic() + 300.0,
        cancel=lambda: time.monotonic() >= cancel_at,
    )

    started = time.monotonic()
    with pytest.raises(JobCancelled) as caught:
        list(adapter.synthesize(context))
    elapsed = time.monotonic() - started
    assert elapsed < 12.0, f"cancellation took {elapsed:.2f}s"
    assert not caught.value.survivors


@pytest.mark.media
def test_a_term_resistant_process_tree_is_still_torn_down(tmp_path, tools, admitted, monkeypatch):
    """SIGTERM alone is not cleanup: the group gets SIGKILL and is confirmed."""
    log = tmp_path / "log.txt"
    monkeypatch.setenv("ANIMALITE_TEST_LOG", str(log))
    binary = _stub_binary(
        tmp_path,
        """
trap '' TERM
echo "started" >> "$ANIMALITE_TEST_LOG"
sleep 60 &
sleep 60
""",
    )
    context, adapter = _stub_context(
        tmp_path, tools, binary=binary, deadline=time.monotonic() + 1.0
    )
    with pytest.raises(JobTimeoutError) as caught:
        list(adapter.synthesize(context))
    assert not caught.value.survivors, (
        f"a TERM-resistant tree outlived teardown: {caught.value.survivors}"
    )


@pytest.mark.media
def test_a_stalled_png_write_is_stopped_by_the_job_deadline(tmp_path, tools, admitted, monkeypatch):
    """B-R2. The anchor writes carried their own 60 s allowance each.

    A job with a 10 s deadline could spend four minutes writing four anchors,
    because the deadline was never passed down. Driven here with a stub standing
    in for ffmpeg, so the stall is deterministic and finite.
    """
    from animalite.contracts.host import ToolIdentity
    from animalite.media.ffmpeg import FFmpegTools

    stalling_ffmpeg = _stub_binary(
        tmp_path, 'echo "started" >> "$ANIMALITE_TEST_LOG"\nsleep 30\n', name="stub-ffmpeg"
    )
    log = tmp_path / "log.txt"
    monkeypatch.setenv("ANIMALITE_TEST_LOG", str(log))
    stub_tools = FFmpegTools(
        ffmpeg=ToolIdentity(name="ffmpeg", available=True, path=str(stalling_ffmpeg)),
        ffprobe=tools.ffprobe,
    )
    context, adapter = _stub_context(
        tmp_path,
        stub_tools,
        binary=_stub_binary(tmp_path, _COPYING_STUB),
        deadline=time.monotonic() + 1.0,
    )

    started = time.monotonic()
    with pytest.raises(JobTimeoutError) as caught:
        list(adapter.synthesize(context))
    elapsed = time.monotonic() - started

    assert elapsed < 12.0, f"the anchor write ran for {elapsed:.2f}s past a 1s deadline"
    assert not caught.value.survivors
    assert log.exists(), "the stub ffmpeg never ran, so this proves nothing"
    assert not list((tmp_path / "scratch" / "rife").glob("*.raw")), (
        "the raw stdin staging file was left behind"
    )


# --- B-R3 / B-R5: the accepted controls and tools are the ones executed -------


@pytest.mark.media
def test_the_tta_control_reaches_the_command_line(tmp_path, tools, admitted, monkeypatch):
    """B-R3. ``tta_spatial=true`` validated, changed the digest, and did nothing.

    Synthesis read ``profile.parameters`` instead of the resolved controls, so
    the request's value never reached argv.
    """
    log = tmp_path / "log.txt"
    monkeypatch.setenv("ANIMALITE_TEST_LOG", str(log))
    context, adapter = _stub_context(
        tmp_path,
        tools,
        binary=_stub_binary(tmp_path, _COPYING_STUB),
        controls={"tta_spatial": True},
    )
    list(adapter.synthesize(context))
    assert " -x" in log.read_text(), log.read_text()


@pytest.mark.media
def test_the_tta_flag_is_absent_by_default(tmp_path, tools, admitted, monkeypatch):
    log = tmp_path / "log.txt"
    monkeypatch.setenv("ANIMALITE_TEST_LOG", str(log))
    context, adapter = _stub_context(tmp_path, tools, binary=_stub_binary(tmp_path, _COPYING_STUB))
    list(adapter.synthesize(context))
    assert " -x" not in log.read_text()


@pytest.mark.media
def test_a_non_boolean_tta_value_reaching_synthesis_is_refused(tmp_path, tools, admitted):
    context, adapter = _stub_context(
        tmp_path,
        tools,
        binary=_stub_binary(tmp_path, _COPYING_STUB),
        controls={"tta_spatial": "false"},
    )
    with pytest.raises(AdapterError, match="tta_spatial"):
        list(adapter.synthesize(context))


@pytest.mark.media
def test_the_thread_allocation_is_applied_to_argv_and_the_environment(
    tmp_path, tools, admitted, monkeypatch
):
    """B-R5. The runtime received no controlled thread environment at all."""
    log = tmp_path / "log.txt"
    monkeypatch.setenv("ANIMALITE_TEST_LOG", str(log))
    monkeypatch.setenv("OMP_NUM_THREADS", "64")  # the host's value must not leak through
    context, adapter = _stub_context(tmp_path, tools, binary=_stub_binary(tmp_path, _COPYING_STUB))
    list(adapter.synthesize(context))

    load, proc, save = rife_job_spec(RIFE_PROFILE.thread_budget)
    text = log.read_text()
    assert f"-j {load}:{proc}:{save}" in text, text
    assert f"OMP_NUM_THREADS={RIFE_PROFILE.thread_budget.inference_threads}" in text, text


@pytest.mark.media
def test_the_adapter_never_rediscovers_its_own_ffmpeg(tmp_path, tools, admitted, monkeypatch):
    """B-R5. A cold envelope pinned the service's tools; the adapter ignored them.

    ``FFmpegTools.discover`` is made to fail, so any rediscovery is an error
    rather than a silent second pair of tools.
    """
    from animalite.media import ffmpeg as ffmpeg_module

    log = tmp_path / "log.txt"
    monkeypatch.setenv("ANIMALITE_TEST_LOG", str(log))

    def refuse(*args, **kwargs):
        raise AssertionError("the adapter rediscovered FFmpeg instead of using context.tools")

    monkeypatch.setattr(ffmpeg_module.FFmpegTools, "discover", staticmethod(refuse))
    context, adapter = _stub_context(tmp_path, tools, binary=_stub_binary(tmp_path, _COPYING_STUB))
    frames = list(adapter.synthesize(context))
    assert len(frames) == 3


# --- B-R6: evidence proportionate to what was observed ------------------------


@pytest.mark.media
def test_device_evidence_stays_pending_without_a_device_observation(
    tmp_path, tools, admitted, monkeypatch
):
    """Observing the configuration is not measuring the device.

    The helper previously returned ``measured`` whenever synthesis completed,
    even though nothing on the host had reported which device ran the model.
    """
    monkeypatch.setenv("ANIMALITE_TEST_LOG", str(tmp_path / "log.txt"))
    context, adapter = _stub_context(tmp_path, tools, binary=_stub_binary(tmp_path, _COPYING_STUB))
    list(adapter.synthesize(context))

    evidence = context.device_evidence
    assert evidence is not None
    assert evidence.inference_device_status is EvidenceStatus.PENDING
    assert evidence.inference_device is None
    assert any("configuration is observed" in note for note in evidence.notes)


@pytest.mark.media
def test_a_vulkan_failure_is_recorded_against_its_own_invocation(
    tmp_path, tools, admitted, monkeypatch
):
    """The claim belongs to the invocation that produced it, not to the attempt."""
    monkeypatch.setenv("ANIMALITE_TEST_LOG", str(tmp_path / "log.txt"))
    binary = _stub_binary(
        tmp_path,
        """
echo "vkCreateInstance failed -9" >&2
"""
        + _COPYING_STUB,
    )
    context, adapter = _stub_context(tmp_path, tools, binary=binary)
    list(adapter.synthesize(context))

    evidence = context.device_evidence
    assert evidence is not None
    assert evidence.inference_device_status is EvidenceStatus.MEASURED
    assert evidence.inference_device == "cpu"
    assert any("animation frame(s) [1]" in note for note in evidence.notes), evidence.notes


@pytest.mark.media
def test_an_all_anchor_request_claims_no_learned_execution(tmp_path, tools, admitted, monkeypatch):
    """Zero invocations is not a CPU-only inference claim; it is no claim."""
    log = tmp_path / "log.txt"
    monkeypatch.setenv("ANIMALITE_TEST_LOG", str(log))
    context, adapter = _stub_context(
        tmp_path, tools, binary=_stub_binary(tmp_path, _COPYING_STUB), frame_count=2
    )
    frames = list(adapter.synthesize(context))

    assert len(frames) == 2
    assert not log.exists(), "an all-anchor request invoked the model"
    evidence = context.device_evidence
    assert evidence is not None
    assert evidence.inference_device_status is EvidenceStatus.NOT_APPLICABLE
    assert any("No learned invocation occurred" in note for note in evidence.notes)


@pytest.mark.media
def test_a_failure_partway_keeps_the_invocations_it_already_made(
    tmp_path, tools, admitted, monkeypatch
):
    """B-R6. A failed attempt is exactly when the argv and counts matter."""
    log = tmp_path / "log.txt"
    monkeypatch.setenv("ANIMALITE_TEST_LOG", str(log))
    binary = _stub_binary(
        tmp_path,
        """
echo "call" >> "$ANIMALITE_TEST_LOG"
if [ "$(wc -l < "$ANIMALITE_TEST_LOG")" -ge 2 ]; then
  echo "synthetic failure" >&2
  exit 3
fi
IN=""
OUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    -0) IN="$2"; shift 2;;
    -o) OUT="$2"; shift 2;;
    *) shift;;
  esac
done
cp "$IN" "$OUT"
""",
    )
    context, adapter = _stub_context(tmp_path, tools, binary=binary, frame_count=4)
    with pytest.raises(AdapterError, match="exit 3"):
        list(adapter.synthesize(context))

    assert any("invocations=2" in note for note in context.notes), context.notes
    assert any("last argv" in note for note in context.notes)
    assert context.device_evidence is not None


# --- model tests: opt-in, installed, admitted ---------------------------------


@pytest.mark.media
@pytest.mark.slow
def test_the_learned_model_synthesizes_motion_rather_than_cross_fading(
    tmp_path, tools, host_admissions
):
    """MR-018 as a measurement, not a declaration.

    A cross-fade between two anchors leaves two half-opacity ghosts, so almost
    no pixel keeps the subject's exact colour. Real temporal synthesis moves the
    subject and preserves it as one solid object.

    A classical warp can also move a subject, so passing this does not by itself
    identify the mechanism -- run ``classical-warp-baseline`` on the same clip
    for that comparison. What it does rule out is a blend.
    """
    require_model_execution()
    from animalite.fixtures.generator import FIXTURE_CLIPS, _render_anchor

    clip = FIXTURE_CLIPS["fixture-two-anchor"]
    left = _render_anchor(clip, 0, 640, 360)
    right = _render_anchor(clip, 8, 640, 360)
    truth = _render_anchor(clip, 4, 640, 360)

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
        tools=tools,
        deadline=time.monotonic() + 900.0,
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

    assert blend_solid < truth_solid * 0.75, (
        f"the blend baseline is not behaving as expected: {blend_solid} vs {truth_solid}"
    )
    assert rife_solid > truth_solid * 0.9, (
        f"RIFE produced {rife_solid} solid-subject pixels vs ground truth "
        f"{truth_solid}; it is not synthesizing a coherent moving subject"
    )
    rife_error = float(np.abs(midpoint - truth.astype(np.float32)).mean())
    blend_error = float(np.abs(blend - truth.astype(np.float32)).mean())
    assert rife_error < blend_error / 2.0, (
        f"RIFE MAE {rife_error:.3f} is not materially better than the "
        f"cross-fade MAE {blend_error:.3f}"
    )


@pytest.mark.media
@pytest.mark.slow
def test_anchors_are_reproduced_exactly_by_the_real_runtime(tmp_path, tools, host_admissions):
    """Approved frames must not be round-tripped through the model (C-05)."""
    require_model_execution()
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
        tools=tools,
        deadline=time.monotonic() + 900.0,
    )
    frames = list(RifeNcnnAdapter().synthesize(context))
    assert np.array_equal(frames[0], left), "the first anchor was not reproduced exactly"
    assert np.array_equal(frames[4], right), "the last anchor was not reproduced exactly"

    evidence = context.device_evidence
    assert evidence is not None
    assert evidence.hardware_acceleration_requested is False
    assert any("-g -1" in note for note in evidence.notes)
    assert any("invocations=3" in note for note in context.notes), context.notes


@pytest.mark.media
@pytest.mark.slow
def test_end_to_end_learned_render_is_labelled_honestly(tmp_path, fixture_anchors, host_admissions):
    """A learned render is still not qualification evidence, for the right reason."""
    require_model_execution()
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
