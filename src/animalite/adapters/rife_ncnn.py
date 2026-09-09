"""RIFE/ncnn CPU adapter: the first learned temporal component (MR-018).

This is a **learned** adapter. Unlike the fixture adapter it declares
``learned_temporal_participation=True`` and is therefore qualification-eligible
in principle -- the benchmark evaluator still refuses a pass without an approved
host, a locked sample and human quality evidence.

Design notes that are load-bearing, each backed by a measurement recorded in
``docs/decisions/DEC-0012-rife-invocation-strategy.md``:

*Execution is admitted before it is attempted.* Verifying the pinned digests
answers "are these the bytes we pinned?". It does not answer "may we execute
them, for this purpose?". :func:`animalite.admission.evaluate_admission` answers
the second question from a recorded decision, and synthesis refuses to launch
anything without one -- not at the qualification evaluator, which is far too
late to be enforcement (CR-024, DEC-0013).

*Explicit per-frame timestep.* The upstream tool also has a directory mode
(``-i``/``-n``) that is far cheaper because it loads the model once. It is not
used, because ``-n`` maps outputs onto the input pair by index arithmetic with a
clamped final pair rather than the uniform sampling this contract needs: asking
for 72 frames from two anchors produced motion that completed by frame ~37 and
then froze on the end anchor, deviating up to 20.15 px from a linear ramp. That
would silently corrupt the section 12.0 frame-index contract and the
source/synthesized/duplicated accounting. Per-frame ``-s`` measured 2.60 px
deviation on the same clip.

*The cost is counted, not hidden.* One subprocess per synthesized frame means
the model is reloaded every frame. Handoff section 5: "If a candidate CLI loads
weights for every invocation, count that cost." The whole loop runs inside the
``temporal_synthesis`` stage, so it is inside the section 12.0 warm boundary.
:meth:`RifeNcnnAdapter.synthesize` additionally records the invocation count and
subprocess wall time as notes on the context, updated after every invocation so
a failed attempt keeps the evidence of what it had already done.

*Anchors are reproduced exactly.* An approved frame at its own animation index
is emitted from the decoded source, never round-tripped through the model.

*Every native call is supervised.* Inference, the anchor PNG writes and the
result decode all run through :func:`animalite.proc.run_capture` under what is
left of the job deadline, with the job's cancel predicate. A private per-call
timeout is not a bound: the generator is pulled synchronously by the encoder, so
while one inference is stalled nothing else in the pipeline can enforce anything.
"""

from __future__ import annotations

import time
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from animalite.adapters.base import AdapterContext
from animalite.adapters.rife_runtime import PINNED_MODELS, RIFE_RELEASE, RifeRuntime
from animalite.admission import evaluate_admission
from animalite.contracts.assets import AnchorSet
from animalite.contracts.enums import (
    EndpointControlMode,
    EngineClass,
    EvidenceStatus,
    IssueSeverity,
    MotionTier,
)
from animalite.contracts.media import OutputSpec
from animalite.contracts.profile import (
    ArtifactIdentity,
    Capabilities,
    EngineProfile,
    LicenseEvaluationRef,
    Resolution,
    ThreadBudget,
)
from animalite.contracts.results import DeviceEvidence
from animalite.contracts.validation import ValidationIssue
from animalite.errors import (
    AdapterError,
    AdmissionDenied,
    CleanupFailed,
    CodeVAL,
    JobCancelled,
    JobTimeoutError,
)
from animalite.media.decode import decode_image_rgb24
from animalite.media.image import write_png_rgb24
from animalite.proc import ProcessCancelled, ProcessTimeout, run_capture
from animalite.resources import apply_thread_environment

__all__ = ["RIFE_ADAPTER_KEY", "RIFE_PROFILE", "RifeNcnnAdapter", "rife_job_spec"]

RIFE_ADAPTER_KEY = "rife-ncnn"

DEFAULT_MODEL = "rife-v4.6"

_SUPPORTED_CONTROLS = ("model", "tta_spatial")

#: Markers the upstream binary prints when Vulkan cannot be initialised. Their
#: presence is positive evidence that no GPU was used *on that invocation*;
#: their absence is not evidence that one was.
_VULKAN_FAILURE_MARKERS = ("vkCreateInstance failed", "vkEnumeratePhysicalDevices failed")

#: Longest stderr kept per invocation. Bounded because it is retained on the
#: attempt record, and a runtime that loops printing must not fill the log.
_STDERR_TAIL = 2000


def _license_evaluation() -> LicenseEvaluationRef:
    """The recorded, deliberately unresolved licence position (CR-024).

    Code and weights are both stated MIT upstream, and the weight statement is
    explicit and separate from the code licence -- which is what MR-012 asks
    for. What is *not* resolved is that the ncnn-format weights shipped in the
    release are conversions, and that repository does not restate weight terms.
    So the mapping stays ``unresolved`` / ``use_eligible=False`` /
    ``resolvable`` until the D-06 reviewer signs it off, rather than being
    asserted as cleared on an implementer's reading of two repositories.

    This reference records the *position*. What blocks execution is the
    admission record (:mod:`animalite.admission`), which is a separate
    artifact- and purpose-bound decision.
    """
    return LicenseEvaluationRef(
        evaluation_id="license-eval:rife-ncnn-20221029",
        subject="rife-ncnn-vulkan 20221029 (MIT code, BSD-3 ncnn) + RIFE v4.6 weights",
        policy_state="pending",
        use_eligible=False,
        eligibility_block_kind="resolvable",
        reviewer=None,
        evidence_url="https://github.com/hzwer/Practical-RIFE#trained-model",
    )


RIFE_PROFILE = EngineProfile(
    profile_id="rife-ncnn-v4.6-cpu",
    display_name="RIFE v4.6 via ncnn, CPU-only (learned temporal interpolation)",
    revision=1,
    adapter_key=RIFE_ADAPTER_KEY,
    engine_class=EngineClass.ML_ASSISTED,
    learned_temporal_participation=True,
    qualification_eligible=True,
    non_qualifying_reason=None,
    supported_tiers=[MotionTier.E3],
    supported_tasks=["temporal_interpolation"],
    supported_controls=list(_SUPPORTED_CONTROLS),
    supported_endpoint_modes=[EndpointControlMode.DETERMINISTIC_STATE],
    supported_resolutions=[
        Resolution(width=640, height=360),
        Resolution(width=320, height=180),
    ],
    min_anchor_count=2,
    max_anchor_count=4,
    max_animation_frame_count=72,
    cpu_only_guaranteed=True,
    # 4 threads on the P-L envelope, allocated to whatever is *runnable* at the
    # time. During an inference the Python parent is blocked in select() and the
    # encoder is blocked reading its stdin, so the whole allocation is the
    # runtime's: `rife_job_spec` turns it into the wrapper's load/proc/save
    # workers, which are threads of that process and are counted here. Between
    # inferences the parent and the encoder are the runnable ones. This is a
    # declared allocation enforced by argv and environment, not a measurement;
    # see `docs/verification/package-a-traceability.md`.
    thread_budget=ThreadBudget(
        total_threads=4, python_threads=1, inference_threads=2, encoder_threads=1
    ),
    parameters={"model": DEFAULT_MODEL, "tta_spatial": False},
    weights=[
        ArtifactIdentity(
            kind="weights",
            identifier=f"{DEFAULT_MODEL}/{name}",
            version="20221029",
            content_hash=f"sha256:{digest}",
            source_url=str(RIFE_RELEASE["source_url"]),
            license_id="MIT (upstream RIFE trained models; see docs/licensing.md)",
            notes="ncnn-format conversion shipped in the pinned release",
        )
        for name, digest in sorted(PINNED_MODELS[DEFAULT_MODEL].file_hashes.items())
    ],
    binaries=[
        ArtifactIdentity(
            kind="binary",
            identifier="rife-ncnn-vulkan",
            version=str(RIFE_RELEASE["version"]),
            content_hash=f"sha256:{RIFE_RELEASE['binary_sha256']}",
            source_url=str(RIFE_RELEASE["source_url"]),
            license_id="MIT (wrapper) + BSD-3-Clause (ncnn)",
            notes="Invoked with -g -1 (CPU). Links libvulkan but needs no GPU.",
        )
    ],
    license_evaluation=_license_evaluation(),
)


def rife_job_spec(budget: ThreadBudget) -> tuple[int, int, int]:
    """Map a thread budget onto the wrapper's ``-j load:proc:save`` workers.

    The pinned wrapper spawns one thread per ``load`` and ``save`` worker plus
    ``proc`` processing threads, all inside the one process. Passing ``1:2:1``
    while also claiming a 4-thread total was not an accounting: it named 4
    runtime threads and left the Python parent and the encoder unaccounted.

    The allocation used instead: load and save get one thread each, and ``proc``
    gets whatever the budget declares for inference, capped so that
    ``load + proc + save`` never exceeds ``total_threads``. During an inference
    the parent is blocked in ``select`` and the encoder is blocked on its stdin,
    so those two threads are not runnable and the runtime may use the whole
    allocation; between inferences the runtime is gone.
    """
    load = save = 1
    ceiling = max(1, budget.total_threads - load - save)
    proc = max(1, min(budget.inference_threads or 1, ceiling))
    return load, proc, save


def _tta_spatial(controls: Mapping[str, object]) -> bool:
    """Read the TTA control, requiring a real boolean.

    ``"false"`` is a true string and ``7`` is a true int, so a truthiness test
    turned both into "enabled" while validation reported nothing. The value has
    to be a ``bool``; anything else is a validation error, not a coercion.
    """
    value = controls.get("tta_spatial", False)
    if isinstance(value, bool):
        return value
    raise AdapterError(
        f"tta_spatial must be a boolean, got {value!r} ({type(value).__name__}); "
        "a string or number is not accepted, because coercing it would silently "
        "enable or disable test-time augmentation"
    )


@dataclass
class _Observations:
    """What the adapter has actually seen so far, kept for failed attempts too.

    Built incrementally rather than at the end of the loop: a run that failed on
    frame 40 had already made 39 observations, and those are exactly the ones
    worth keeping.
    """

    model_name: str
    architecture: str
    job_spec: tuple[int, int, int]
    invocations: int = 0
    subprocess_seconds: float = 0.0
    #: Animation frames whose invocation printed a Vulkan initialisation
    #: failure. Recorded per frame because the claim belongs to the invocation
    #: that produced it, not to the attempt as a whole.
    vulkan_failure_frames: list[int] = field(default_factory=list)
    first_stderr: str = ""
    last_argv: tuple[str, ...] = ()
    binary_digest: str | None = None

    def record(self, argv: list[str], elapsed_seconds: float) -> None:
        """Note one invocation that actually launched, however it ended."""
        self.invocations += 1
        self.subprocess_seconds += elapsed_seconds
        self.last_argv = tuple(argv)

    def notes(self) -> list[str]:
        load, proc, save = self.job_spec
        entries = [
            f"rife model={self.model_name} ({self.architecture}) "
            f"invocations={self.invocations} -j {load}:{proc}:{save}",
        ]
        if self.binary_digest:
            entries.append(f"rife binary digest verified: {self.binary_digest}")
        if self.invocations:
            entries.append(
                f"rife subprocess wall={self.subprocess_seconds:.3f}s "
                f"({self.subprocess_seconds / self.invocations:.3f}s per synthesized "
                "frame, including one model load each)"
            )
            entries.append(f"rife last argv: {' '.join(self.last_argv)}")
        if self.vulkan_failure_frames:
            entries.append(
                "rife reported a Vulkan initialisation failure on animation frame(s) "
                f"{self.vulkan_failure_frames[:8]}"
                f"{' (truncated)' if len(self.vulkan_failure_frames) > 8 else ''}"
            )
        return entries

    def device_evidence(self) -> DeviceEvidence:
        """Device evidence proportionate to what was actually observed.

        Three distinct states, because collapsing them is how "measured" gets
        claimed for something nobody measured:

        * no invocation at all -- nothing learned ran, so there is no CPU-only
          inference claim to make and none is made;
        * invocations that reported a Vulkan initialisation failure -- positive
          evidence that no GPU path existed on this host;
        * invocations with no such message -- the *configuration* was observed
          (``-g -1``, argv recorded), the *device* was not measured, so the
          status stays pending.
        """
        load, proc, save = self.job_spec
        configuration = [
            "Inference invoked with -g -1, which selects ncnn's CPU path "
            "explicitly. Automatic device selection is never used.",
            f"Thread allocation passed as -j {load}:{proc}:{save} and pinned in the "
            "child environment; a declared allocation, not a measured occupancy.",
            "The encoder process is alive throughout synthesis and consumes this "
            "generator, so it surrounds these invocations rather than following "
            "them; it is blocked on its stdin while an inference runs.",
        ]
        if self.invocations == 0:
            return DeviceEvidence(
                inference_device_status=EvidenceStatus.NOT_APPLICABLE,
                inference_device=None,
                encoder_device="cpu",
                hardware_acceleration_requested=False,
                network_calls_observed_status=EvidenceStatus.PENDING,
                notes=[
                    "No learned invocation occurred in this attempt: every "
                    "requested animation frame was an approved anchor, emitted "
                    "from the decoded source. Nothing here evidences learned "
                    "temporal capability.",
                    *configuration,
                ],
            )
        if self.vulkan_failure_frames:
            return DeviceEvidence(
                inference_device_status=EvidenceStatus.MEASURED,
                inference_device="cpu",
                encoder_device="cpu",
                hardware_acceleration_requested=False,
                network_calls_observed_status=EvidenceStatus.PENDING,
                notes=[
                    "Positive evidence: the runtime could not create a Vulkan "
                    "instance on animation frame(s) "
                    f"{self.vulkan_failure_frames[:8]}, so a GPU path was "
                    "unavailable on those invocations, not merely unselected. "
                    f"First stderr: {self.first_stderr[:200]!r}",
                    f"{len(self.vulkan_failure_frames)} of {self.invocations} "
                    "invocation(s) reported it; the remainder are evidenced by "
                    "configuration only.",
                    *configuration,
                ],
            )
        return DeviceEvidence(
            inference_device_status=EvidenceStatus.PENDING,
            inference_device=None,
            encoder_device="cpu",
            hardware_acceleration_requested=False,
            network_calls_observed_status=EvidenceStatus.PENDING,
            notes=[
                f"{self.invocations} invocation(s) observed with the CPU device "
                "selected by argument. No Vulkan initialisation failure was seen, "
                "so nothing on this host measured which device executed the "
                "inference: the configuration is observed, the device is not.",
                *configuration,
            ],
        )


class RifeNcnnAdapter:
    """Drives the pinned rife-ncnn-vulkan executable, CPU-only."""

    key = RIFE_ADAPTER_KEY

    def __init__(self, runtime: RifeRuntime | None = None) -> None:
        self._runtime = runtime

    # ------------------------------------------------------------------ helpers

    @property
    def runtime(self) -> RifeRuntime:
        if self._runtime is None:
            self._runtime = RifeRuntime.discover()
        return self._runtime

    @staticmethod
    def _model_name(profile: EngineProfile, controls: Mapping[str, object]) -> str:
        return str(controls.get("model", profile.parameters.get("model", DEFAULT_MODEL)))

    @staticmethod
    def _required_timesteps(anchors: AnchorSet, output: OutputSpec) -> list[float]:
        """Timesteps the request will actually ask the model for.

        Returns what it can: a frame with no bracketing anchor pair is skipped
        rather than raising, because this runs *during validation* of a request
        that may well be invalid. Raising here replaced a precise anchor-range
        error with a stack trace.
        """
        indices = anchors.indices
        steps: list[float] = []
        for frame_index in range(output.animation_frame_count):
            if frame_index in indices:
                continue
            left = [i for i in indices if i <= frame_index]
            right = [i for i in indices if i > frame_index]
            if not left or not right:
                continue
            steps.append((frame_index - max(left)) / (min(right) - max(left)))
        return steps

    # -------------------------------------------------------------- section 6.3

    def capabilities(self, profile: EngineProfile) -> Capabilities:
        model = PINNED_MODELS.get(self._model_name(profile, {}))
        runtime = self.runtime
        load, proc, save = rife_job_spec(profile.thread_budget)
        notes = [
            "Learned temporal interpolation: the model estimates flow between "
            "two approved anchors and synthesizes the intermediate frame.",
            "CPU-only: invoked with -g -1. The binary links libvulkan and "
            "attempts instance creation at startup regardless; a failure there "
            "is recorded as positive evidence, for that invocation, that no GPU "
            "path was available.",
            "One subprocess per synthesized frame, so the model is reloaded per "
            "frame. That cost is inside the timed synthesis stage and is "
            "reported, not subtracted (handoff section 5).",
            f"Threads: -j {load}:{proc}:{save} within a "
            f"{profile.thread_budget.total_threads}-thread budget, pinned in the "
            "child environment as well as on the command line.",
            "Cancellation and the job deadline bound each native invocation, "
            "not only the gap between frames.",
            "Execution requires a recorded admission decision covering these "
            "exact artifacts and the run's purpose; verification of the pinned "
            "digests is a separate, weaker check.",
        ]
        if model is not None and not model.supports_arbitrary_timestep:
            notes.append(
                f"{model.name} is midpoint-only and is rejected for any timestep other than 0.5."
            )
        if not runtime.available:
            notes.append(
                "Runtime NOT INSTALLED on this host: no weights or executable "
                "resolved. Validation will reject execution."
            )
        return Capabilities(
            profile_id=profile.profile_id,
            adapter_key=self.key,
            engine_class=profile.engine_class,
            learned_temporal_participation=True,
            qualification_eligible=profile.qualification_eligible,
            non_qualifying_reason=profile.non_qualifying_reason,
            supported_tiers=list(profile.supported_tiers),
            supported_tasks=list(profile.supported_tasks),
            supported_controls=list(_SUPPORTED_CONTROLS),
            supported_endpoint_modes=list(profile.supported_endpoint_modes),
            supported_resolutions=list(profile.supported_resolutions),
            min_anchor_count=profile.min_anchor_count,
            max_anchor_count=profile.max_anchor_count,
            max_animation_frame_count=profile.max_animation_frame_count,
            cpu_only_guaranteed=True,
            supports_safe_cancel=True,
            notes=notes,
        )

    def validate(
        self,
        profile: EngineProfile,
        anchors: AnchorSet,
        output: OutputSpec,
        controls: dict[str, float | int | str | bool],
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []

        for name in controls:
            if name not in _SUPPORTED_CONTROLS:
                issues.append(
                    ValidationIssue(
                        code=CodeVAL.CONTROL_UNSUPPORTED,
                        severity=IssueSeverity.ERROR,
                        field_path=f"controls.{name}",
                        message=f"the RIFE adapter does not implement control {name!r}",
                        remediation=(
                            f"Remove the control. Supported: {', '.join(_SUPPORTED_CONTROLS)}."
                        ),
                    )
                )

        try:
            _tta_spatial(controls)
        except AdapterError as exc:
            issues.append(
                ValidationIssue(
                    code=CodeVAL.CONTROL_VALUE_INVALID,
                    severity=IssueSeverity.ERROR,
                    field_path="controls.tta_spatial",
                    message=str(exc),
                    remediation=(
                        "Pass true or false. Test-time augmentation multiplies "
                        "inference cost, so it is never inferred from a string "
                        "or a number."
                    ),
                )
            )

        model_name = self._model_name(profile, controls)
        model = PINNED_MODELS.get(model_name)
        if model is None:
            issues.append(
                ValidationIssue(
                    code=CodeVAL.RUNTIME_MODEL_UNKNOWN,
                    severity=IssueSeverity.ERROR,
                    field_path="controls.model",
                    message=f"model {model_name!r} is not pinned",
                    remediation=(
                        f"Use a pinned model: {', '.join(sorted(PINNED_MODELS))}. "
                        "An unpinned checkpoint has no verified digest."
                    ),
                )
            )
            return issues

        # The rule that stops a silently-wrong result: a midpoint-only model
        # asked for any other timestep returns a plausible but temporally
        # incorrect frame.
        if not model.supports_arbitrary_timestep:
            needed = {round(t, 6) for t in self._required_timesteps(anchors, output)}
            off_midpoint = sorted(t for t in needed if abs(t - 0.5) > 1e-9)
            if off_midpoint:
                issues.append(
                    ValidationIssue(
                        code=CodeVAL.RUNTIME_TIMESTEP_UNSUPPORTED,
                        severity=IssueSeverity.ERROR,
                        field_path="controls.model",
                        message=(
                            f"model {model_name!r} ({model.architecture}) is "
                            f"midpoint-only, but this request needs "
                            f"{len(off_midpoint)} non-0.5 timestep(s), e.g. "
                            f"{off_midpoint[:3]}. It is excluded from use rather "
                            "than trusted off-midpoint."
                        ),
                        remediation=("Use rife-v4.6, which honours an arbitrary timestep."),
                    )
                )

        runtime = self.runtime
        verification = runtime.verify(model_name)
        if not verification.usable:
            for problem in verification.problems:
                issues.append(
                    ValidationIssue(
                        code=CodeVAL.RUNTIME_UNVERIFIED,
                        severity=IssueSeverity.ERROR,
                        field_path="environment.rife_runtime",
                        message=problem,
                        remediation=(
                            "Install the pinned release with `animalite runtime "
                            "fetch --install`, or point ANIMALITE_RIFE_BIN / "
                            "ANIMALITE_RIFE_MODELS at a verified install."
                        ),
                    )
                )

        evaluation = profile.license_evaluation
        if evaluation is not None and not evaluation.use_eligible:
            issues.append(
                ValidationIssue(
                    code=CodeVAL.LICENCE_NOT_CLEARED,
                    severity=IssueSeverity.WARNING,
                    field_path="profile.license_evaluation",
                    message=(
                        f"licence evaluation {evaluation.evaluation_id} is "
                        f"{evaluation.policy_state!r} with use_eligible=False "
                        f"({evaluation.eligibility_block_kind})"
                    ),
                    remediation=(
                        "This records the position; what blocks execution is the "
                        "admission decision (VAL-ADMISSION-*). Resolve the D-06 "
                        "review and record the disposition against these exact "
                        "artifacts and purposes."
                    ),
                )
            )
        return issues

    # ------------------------------------------------------------------ synthesis

    def synthesize(self, context: AdapterContext) -> Iterator[NDArray[np.uint8]]:
        output = context.output
        anchors = context.anchors
        indices = anchors.indices
        profile = context.profile
        # Defaults with the request's validated overrides applied: the one
        # resolved mapping validation checked. Reading `profile.parameters`
        # here meant `tta_spatial=true` validated, changed the settings digest,
        # and then never reached the command line.
        controls = context.effective_controls()
        model_name = self._model_name(profile, controls)
        tta = _tta_spatial(controls)

        # Admission first: before the digests, before the scratch directory,
        # before any file is written. A denied run must not be distinguishable
        # from "never started" on disk.
        admission = evaluate_admission(profile, context.purpose)
        if not admission.admitted:
            raise AdmissionDenied(
                f"execution of {profile.profile_id!r} for purpose "
                f"{context.purpose.value!r} is not admitted ({admission.summary}). "
                "Nothing was launched."
            )

        model = PINNED_MODELS.get(model_name)
        if model is None:
            raise AdapterError(f"model {model_name!r} is not pinned; nothing was launched")

        runtime = self.runtime
        verification = runtime.verify(model_name)
        if not verification.usable:
            raise AdapterError("RIFE runtime is not usable: " + "; ".join(verification.problems))
        binary = runtime.binary_path
        model_dir = runtime.model_dir(model_name)
        if binary is None or model_dir is None:  # pragma: no cover - verify() covers it
            raise AdapterError("RIFE runtime resolved inconsistently")

        budget = profile.thread_budget
        load, proc, save = rife_job_spec(budget)
        observations = _Observations(
            model_name=model_name,
            architecture=model.architecture,
            job_spec=(load, proc, save),
            binary_digest=f"sha256:{RIFE_RELEASE['binary_sha256']}",
        )
        context.device_evidence = observations.device_evidence()
        environment = apply_thread_environment(budget)

        scratch = context.scratch_dir / "rife"
        scratch.mkdir(parents=True, exist_ok=True)

        # Normalized anchors on disk: the runtime's interface is file-based, and
        # these are the exact pixels the model sees. Bounded by the job deadline
        # like everything else -- these used to carry a private 60 s allowance
        # each, which a job with a 10 s deadline would happily spend.
        anchor_paths: dict[int, Path] = {}
        for index in indices:
            context.raise_if_cancelled(f"writing anchor {index}")
            path = scratch / f"anchor_{index:04d}.png"
            write_png_rgb24(
                context.tools,
                context.anchor_frames[index],
                path,
                timeout=context.remaining_seconds(),
                cancel=context.cancel,
                thread_budget=budget,
            )
            anchor_paths[index] = path

        for frame_index in range(output.animation_frame_count):
            context.raise_if_cancelled(f"synthesizing animation frame {frame_index}")

            if frame_index in indices:
                # An approved anchor is emitted exactly, never re-synthesized.
                yield np.ascontiguousarray(context.anchor_frames[frame_index])
                continue

            left = max(i for i in indices if i <= frame_index)
            right = min(i for i in indices if i > frame_index)
            timestep = (frame_index - left) / (right - left)
            destination = scratch / f"synth_{frame_index:04d}.png"

            argv = [
                str(binary),
                "-0",
                str(anchor_paths[left]),
                "-1",
                str(anchor_paths[right]),
                "-o",
                str(destination),
                "-m",
                str(model_dir),
                "-s",
                f"{timestep:.8f}",
                "-g",
                "-1",  # CPU. Never 'auto'.
                "-j",
                f"{load}:{proc}:{save}",
            ]
            if tta:
                argv.append("-x")

            # Checked before launching, not after: an expired deadline must
            # start nothing rather than grant one more full-length inference.
            budget_left = context.remaining_seconds()
            started = time.perf_counter()
            launched = False
            try:
                completed = run_capture(
                    argv,
                    timeout=budget_left,
                    cancel=context.cancel,
                    env=environment,
                )
                launched = True
            except ProcessTimeout as exc:
                launched = True
                raise JobTimeoutError(
                    f"the job deadline expired during RIFE inference for animation "
                    f"frame {frame_index} (t={timestep:.6f}) after "
                    f"{budget_left:.3f}s; the process group was torn down and "
                    "nothing was published",
                    survivors=exc.survivors,
                ) from exc
            except ProcessCancelled as exc:
                launched = True
                raise JobCancelled(
                    f"cancelled during RIFE inference for animation frame {frame_index}: {exc}",
                    survivors=exc.survivors,
                ) from exc
            finally:
                # Recorded for a timed-out or cancelled inference too: it ran,
                # it cost that time, and a failed attempt keeps what it saw. Not
                # recorded when the launch itself failed, because counting a
                # process that never started as an invocation would put a
                # fabricated observation on the attempt.
                if launched:
                    observations.record(argv, time.perf_counter() - started)
                    context.device_evidence = observations.device_evidence()
                    context.notes[:] = observations.notes()

            stderr_text = completed.stderr.decode("utf-8", "replace")
            if not observations.first_stderr:
                observations.first_stderr = stderr_text.strip()[:_STDERR_TAIL]
            if any(marker in stderr_text for marker in _VULKAN_FAILURE_MARKERS):
                observations.vulkan_failure_frames.append(frame_index)
            context.device_evidence = observations.device_evidence()

            if completed.survivors:
                raise CleanupFailed(
                    f"RIFE inference for animation frame {frame_index} left process "
                    f"group(s) {list(completed.survivors)} alive after teardown",
                    survivors=completed.survivors,
                )
            if completed.returncode != 0 or not destination.is_file():
                raise AdapterError(
                    f"RIFE failed on animation frame {frame_index} "
                    f"(t={timestep:.6f}): exit {completed.returncode}; "
                    f"{stderr_text.strip()[-500:]}"
                )

            frame = decode_image_rgb24(
                context.tools,
                destination,
                width=output.width,
                height=output.height,
                timeout=context.remaining_seconds(),
                cancel=context.cancel,
                thread_budget=budget,
            )
            # Reclaim scratch as we go: a 72-frame clip would otherwise leave
            # ~70 full-resolution PNGs behind for every attempt.
            destination.unlink(missing_ok=True)
            yield frame

        context.device_evidence = observations.device_evidence()
        context.notes[:] = observations.notes()
