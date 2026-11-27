"""Local execution service implementing the section 6.3 lifecycle.

``validate`` / ``estimate`` / ``submit`` / ``status`` / ``cancel`` / ``collect``
/ ``capabilities``. The CLI and the benchmark runner both call *this* class --
there is no second execution path (handoff rule 3).

Concurrency: one render job runs at a time, matching the P-L policy of a single
render job on the low-spec host. ``submit`` returns immediately with a job id;
the work runs on one worker thread whose native children are process-group
managed.
"""

from __future__ import annotations

import shutil
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from animalite.adapters.base import AdapterContext
from animalite.adapters.registry import Registry, default_registry
from animalite.contracts.base import sha256_file
from animalite.contracts.enums import (
    EvidenceStatus,
    FailureCategory,
    JobState,
    Stage,
)
from animalite.contracts.estimate import ResourceEstimate
from animalite.contracts.job import (
    AttemptRecord,
    CancelResult,
    FailureRecord,
    JobStatus,
    RenderRequest,
)
from animalite.contracts.media import FrameAccounting
from animalite.contracts.profile import Capabilities, EngineProfile, ThreadBudget
from animalite.contracts.results import (
    DeviceEvidence,
    MemoryObservation,
    OutputManifest,
    StageTiming,
)
from animalite.contracts.validation import ValidationReport
from animalite.core.attempts import AttemptDirs, AttemptStore, new_attempt_id
from animalite.core.environment import capture_environment
from animalite.core.logging import AttemptLogger, StructuredLogger, utc_now
from animalite.core.validation import validate_request
from animalite.errors import (
    AdapterError,
    AnimaLiteError,
    CleanupFailed,
    JobCancelled,
    JobTimeoutError,
    OutputInvalidError,
    ValidationRejected,
)
from animalite.media.cadence import expand_to_delivery, frame_accounting
from animalite.media.decode import decode_image_rgb24
from animalite.media.encode import encode_delivery_stream
from animalite.media.ffmpeg import FFmpegTools
from animalite.media.probe import probe_output, validate_output
from animalite.resources import MemorySampler

__all__ = ["OUTPUT_FILENAME", "LocalExecutionService"]

OUTPUT_FILENAME = "output.mp4"


class _Job:
    """Mutable in-process state for one submitted job."""

    def __init__(self, record: AttemptRecord, dirs: AttemptDirs) -> None:
        self.record = record
        self.dirs = dirs
        self.cancel_event = threading.Event()
        self.done_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.stage: Stage | None = None
        self.lock = threading.Lock()


def _device_evidence_before_adapter(profile: EngineProfile | None) -> DeviceEvidence:
    """The device evidence an attempt carries until its adapter reports.

    Three cases, kept apart because collapsing them produced a false record:
    an attempt that never reached an adapter, a profile that runs no inference
    runtime at all, and a learned profile whose adapter has not (yet) reported.
    The last one is *pending*, never ``not_applicable``: a failed learned
    attempt used to inherit the fixture path's "runs no inference runtime" note.
    """
    shared = [
        "The encoder is invoked with software codecs only; no hardware "
        "acceleration flag is passed.",
        "Network isolation is not asserted by this package; AT-056's offline "
        "rerun is a Package C activity.",
    ]
    if profile is None:
        return DeviceEvidence(
            inference_device_status=EvidenceStatus.PENDING,
            inference_device=None,
            network_calls_observed_status=EvidenceStatus.PENDING,
            notes=["The attempt did not reach an adapter, so no device was observed.", *shared],
        )
    if not profile.learned_temporal_participation:
        return DeviceEvidence(
            inference_device_status=EvidenceStatus.NOT_APPLICABLE,
            inference_device=None,
            network_calls_observed_status=EvidenceStatus.PENDING,
            notes=[
                f"Profile {profile.profile_id!r} declares no learned temporal "
                "participation and executes no inference runtime, so there is no "
                "CPU-only inference claim to evidence (MR-015 remains open for "
                "the learned path).",
                *shared,
            ],
        )
    return DeviceEvidence(
        inference_device_status=EvidenceStatus.PENDING,
        inference_device=None,
        network_calls_observed_status=EvidenceStatus.PENDING,
        notes=[
            f"Profile {profile.profile_id!r} declares learned temporal "
            "participation, and its adapter recorded no device observation for "
            "this attempt. Absent evidence stays pending; it is not a CPU-only "
            "claim and not a not-applicable one.",
            *shared,
        ],
    )


class LocalExecutionService:
    """Single-host execution service. One render job at a time."""

    def __init__(
        self,
        workspace: Path,
        *,
        registry: Registry | None = None,
        tools: FFmpegTools | None = None,
        logger: StructuredLogger | None = None,
    ) -> None:
        self.workspace = Path(workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.registry = registry if registry is not None else default_registry()
        self.tools = tools if tools is not None else FFmpegTools.discover()
        self.store = AttemptStore(self.workspace)
        self._logger = logger if logger is not None else StructuredLogger(enabled=False)
        self._jobs: dict[str, _Job] = {}
        self._render_lock = threading.Lock()
        self._registry_lock = threading.Lock()

    # ---------------------------------------------------------------- section 6.3

    def capabilities(self, engine_profile_id: str) -> Capabilities:
        profile = self.registry.profile(engine_profile_id)
        return self.registry.adapter_for(profile).capabilities(profile)

    def validate(self, request: RenderRequest) -> ValidationReport:
        return validate_request(request, self.registry, tools=self.tools)

    def estimate(self, request: RenderRequest) -> ResourceEstimate:
        """Device-class-agnostic estimate. Heuristic, and it says so.

        The basis string exists so an estimate is never mistaken for an
        observation: nothing here has been measured on the requesting host.
        """
        profile = self.registry.profile(request.engine_profile_id)
        output = request.output
        pixels = output.width * output.height
        # Rough per-frame cost of the blend + encode on a modern CPU core. This
        # is a placeholder scale factor, not a measurement.
        per_frame_seconds = pixels / 40_000_000.0
        render_seconds = per_frame_seconds * output.delivery_frame_count
        frame_bytes = pixels * 3
        return ResourceEstimate(
            profile_id=profile.profile_id,
            request_id=request.request_id,
            reusable_setup_units=[],
            reusable_integration_overhead_hours=0.0,
            preparation_active_seconds=0.0,
            preparation_wall_seconds=0.0,
            cold_start_seconds=1.0,
            preview_wall_seconds=0.0,
            render_encode_wall_seconds=render_seconds,
            input_anchor_count=request.anchors.count,
            animation_frame_count=output.animation_frame_count,
            delivery_frame_count=output.delivery_frame_count,
            # Bounded by the anchors held in memory plus a few working frames;
            # the pipeline streams, so this does not scale with clip length.
            peak_application_memory_bytes=frame_bytes * (request.anchors.count + 4),
            thread_count=profile.thread_budget.total_threads,
            scratch_storage_mb=round(frame_bytes * 2 / 1_000_000, 3),
            estimated_cost=None,
            basis=(
                "static heuristic from output geometry and frame count; NOT measured "
                "on this host and not evidence for any section 12.0 target"
            ),
            is_measured=False,
        )

    def submit(self, request: RenderRequest) -> str:
        """Validate, allocate an immutable attempt and start the worker.

        Returns the job id. A request that fails validation still gets an
        attempt directory and a persisted failed record, so a rejection is
        visible in the ledger rather than vanishing.
        """
        profile = self._profile_or_placeholder(request)
        attempt_id = new_attempt_id()
        dirs = self.store.allocate(attempt_id)
        record = AttemptRecord(
            attempt_id=attempt_id,
            job_id=attempt_id,
            request=request,
            profile=profile,
            settings_digest=request.settings_digest(),
            state=JobState.QUEUED,
            created_at=utc_now(),
            attempt_dir=str(dirs.root),
            parent_attempt_id=request.parent_attempt_id,
            retry_index=self._retry_index(request.parent_attempt_id),
            environment=capture_environment(profile.thread_budget, self.tools),
        )
        self.store.save(record)

        job = _Job(record, dirs)
        self._jobs[attempt_id] = job
        job.thread = threading.Thread(
            target=self._run_job, args=(job,), name=f"animalite-{attempt_id}", daemon=True
        )
        job.thread.start()
        return attempt_id

    def status(self, job_id: str) -> JobStatus:
        job = self._job(job_id)
        with job.lock:
            record = job.record
            return JobStatus(
                job_id=job_id,
                attempt_id=record.attempt_id,
                state=record.state,
                progress=record.progress,
                stage=job.stage.value if job.stage else None,
                failure=record.failure,
                output_path=record.output.path if record.output else None,
                started_at=record.started_at,
                finished_at=record.finished_at,
            )

    def cancel(self, job_id: str) -> CancelResult:
        """Request cancellation. Reports the real granularity, not an instant stop."""
        job = self._job(job_id)
        with job.lock:
            state = job.record.state
        if state.is_terminal:
            return CancelResult(
                job_id=job_id,
                accepted=False,
                state=state,
                safe_cancellation_supported=True,
                message=f"job is already {state.value}; nothing to cancel",
            )
        job.cancel_event.set()
        return CancelResult(
            job_id=job_id,
            accepted=True,
            state=state,
            safe_cancellation_supported=True,
            message=(
                "cancellation requested; it takes effect at the next animation-frame "
                "boundary or when the encoder process group is torn down. No partial "
                "output is published."
            ),
        )

    def collect(self, job_id: str) -> AttemptRecord:
        """Return the final immutable attempt record, waiting for completion."""
        job = self._job(job_id)
        job.done_event.wait()
        return self.store.load(job_id)

    def wait(self, job_id: str, timeout: float | None = None) -> bool:
        return self._job(job_id).done_event.wait(timeout)

    def render_blocking(self, request: RenderRequest) -> AttemptRecord:
        """Convenience wrapper: submit and wait. Used by the CLI and benchmark."""
        return self.collect(self.submit(request))

    # ------------------------------------------------------------------ internals

    def _job(self, job_id: str) -> _Job:
        try:
            return self._jobs[job_id]
        except KeyError as exc:
            raise KeyError(f"unknown job id {job_id!r}") from exc

    def _profile_or_placeholder(self, request: RenderRequest) -> EngineProfile:
        """Resolve the profile, or synthesize a rejected-placeholder for the record."""
        try:
            return self.registry.profile(request.engine_profile_id)
        except AnimaLiteError:
            from animalite.adapters.fixture import FIXTURE_PROFILE

            return FIXTURE_PROFILE.model_copy(
                update={
                    "profile_id": f"unresolved:{request.engine_profile_id}",
                    "display_name": "UNRESOLVED PROFILE (request rejected at validation)",
                    "non_qualifying_reason": "profile could not be resolved",
                }
            )

    def _retry_index(self, parent_attempt_id: str | None) -> int:
        if parent_attempt_id is None:
            return 0
        try:
            return self.store.load(parent_attempt_id).retry_index + 1
        except (OSError, ValueError):
            return 1

    def _finish(
        self,
        job: _Job,
        *,
        state: JobState,
        stages: list[StageTiming],
        failure: FailureRecord | None = None,
        output: OutputManifest | None = None,
        memory: MemoryObservation | None = None,
        frame_accounting_value: FrameAccounting | None = None,
        device_evidence: DeviceEvidence | None = None,
        cleanup_survivor_groups: Sequence[int] = (),
        notes: Sequence[str] = (),
    ) -> None:
        with job.lock:
            update: dict[str, Any] = {
                "state": state,
                "finished_at": utc_now(),
                "stages": stages,
                "failure": failure,
                "output": output,
                "progress": 1.0 if state is JobState.SUCCEEDED else job.record.progress,
            }
            if memory is not None:
                update["memory"] = memory
            if frame_accounting_value is not None:
                update["frame_accounting"] = frame_accounting_value
            if device_evidence is not None:
                update["device_evidence"] = device_evidence
            if cleanup_survivor_groups:
                update["cleanup_survivor_groups"] = list(cleanup_survivor_groups)
            if notes:
                update["notes"] = list(notes)
            job.record = job.record.model_copy(update=update)
            self.store.save(job.record)
        job.done_event.set()

    def _run_job(self, job: _Job) -> None:
        with self._render_lock:
            self._execute(job)

    def _execute(self, job: _Job) -> None:
        request = job.record.request
        dirs = job.dirs
        stages: list[StageTiming] = []
        survivor_groups: list[int] = []
        notes: list[str] = []
        context: AdapterContext | None = None
        sampler = MemorySampler()
        logger = AttemptLogger(job.record.attempt_id, dirs.log_path, console=self._logger)
        # Replaced with a profile-specific default as soon as the profile is
        # resolved. Until then the attempt has not reached an adapter, and that
        # is what this says -- the previous unconditional "runs no inference
        # runtime" note was copied onto failed *learned* attempts, asserting
        # something about a run that had launched a model.
        device_evidence = _device_evidence_before_adapter(None)
        deadline = time.monotonic() + request.timeout_seconds

        def remaining() -> float:
            """Time left on the job deadline, or a timeout if there is none.

            The old ``max(0.1, ...)`` floor renewed a 100 ms allowance to every
            subsequent operation, so an expired deadline still launched the next
            decode, encode or probe. An expired deadline now stops the pipeline
            before another native child is started.
            """
            left = deadline - time.monotonic()
            if left <= 0:
                raise JobTimeoutError(
                    f"the job deadline of {request.timeout_seconds:.3f}s expired during "
                    f"{job.stage.value if job.stage else 'execution'}; no further work "
                    "was started and nothing was published"
                )
            return left

        def timed(stage: Stage) -> _StageTimer:
            job.stage = stage
            return _StageTimer(stage, stages, logger)

        try:
            with job.lock:
                job.record = job.record.model_copy(
                    update={"state": JobState.RUNNING, "started_at": utc_now()}
                )
                self.store.save(job.record)
            logger.emit(
                "attempt.started",
                profile_id=job.record.profile.profile_id,
                settings_digest=job.record.settings_digest,
                qualification_eligible=job.record.profile.qualification_eligible,
            )
            sampler.start()

            with timed(Stage.VALIDATE):
                report = self.validate(request)
                if not report.valid:
                    raise ValidationRejected(report.summary(), report.error_codes)

            profile = self.registry.profile(request.engine_profile_id)
            adapter = self.registry.adapter_for(profile)
            device_evidence = _device_evidence_before_adapter(profile)

            with timed(Stage.DECODE_ANCHORS):
                anchor_frames = self._decode_anchors(
                    request,
                    remaining(),
                    cancel=job.cancel_event.is_set,
                    thread_budget=profile.thread_budget,
                )

            self._check_cancelled(job)
            accounting = frame_accounting(request.anchors, request.output)

            produced = dirs.work / OUTPUT_FILENAME
            encoder_stderr = dirs.work / "encoder.stderr.log"

            context = AdapterContext(
                anchor_frames=anchor_frames,
                output=request.output,
                anchors=request.anchors,
                profile=profile,
                scratch_dir=dirs.work,
                tools=self.tools,
                controls=profile.effective_controls(request.controls),
                cancel_requested=job.cancel_event,
                deadline=deadline,
                cancel=job.cancel_event.is_set,
                purpose=request.execution_purpose,
            )
            # The adapter is a generator consumed by the encoder writer, so the
            # two stages interleave. `synthesis_seconds` accumulates the time
            # actually spent inside the adapter, and it is subtracted from the
            # encode stage below -- otherwise every second of model inference
            # would be reported as encoder time (NFR-028: no stage may be
            # misattributed or hidden).
            synthesis_seconds = [0.0]
            frames = self._counted_frames(
                job, adapter.synthesize(context), request, synthesis_seconds
            )

            job.stage = Stage.ENCODE
            encode_started = time.perf_counter()
            logger.emit("stage.start", stage=Stage.ENCODE.value)
            try:
                encoded = encode_delivery_stream(
                    self.tools,
                    expand_to_delivery(frames, request.output),
                    request.output,
                    produced,
                    thread_budget=profile.thread_budget,
                    timeout_seconds=remaining(),
                    stderr_path=encoder_stderr,
                    cancel=job.cancel_event.is_set,
                )
                if encoded.survivors:
                    # A leaked encoder is a failed attempt, not a note on a
                    # successful one. It still holds CPU, memory and descriptors,
                    # so continuing to probe and publish would report a clean run
                    # that was not clean. Raised inside the try so the finally
                    # below still attributes the synthesis/encode split.
                    raise CleanupFailed(
                        f"encoder process group(s) {list(encoded.survivors)} were still "
                        "alive after teardown; the cleanup guarantee did not hold, so "
                        "this attempt publishes nothing",
                        survivors=encoded.survivors,
                    )
            finally:
                pipeline_seconds = time.perf_counter() - encode_started
                stages.append(
                    StageTiming(
                        stage=Stage.TEMPORAL_SYNTHESIS,
                        wall_seconds=round(synthesis_seconds[0], 6),
                        inside_timing_boundary=True,
                        detail="measured inside the adapter generator",
                    )
                )
                stages.append(
                    StageTiming(
                        stage=Stage.ENCODE,
                        wall_seconds=round(max(0.0, pipeline_seconds - synthesis_seconds[0]), 6),
                        inside_timing_boundary=True,
                        detail=(
                            "streaming encode, exclusive of adapter time pulled "
                            "through the same pipeline"
                        ),
                    )
                )
                logger.emit(
                    "stage.end",
                    stage=Stage.ENCODE.value,
                    duration_seconds=round(pipeline_seconds, 6),
                    synthesis_seconds=round(synthesis_seconds[0], 6),
                )

            self._check_cancelled(job)

            if context.device_evidence is not None:
                device_evidence = context.device_evidence
            for note in context.notes:
                logger.emit("adapter.note", note=note)
            notes.extend(context.notes)

            with timed(Stage.VALIDATE_OUTPUT):
                probe = probe_output(
                    self.tools, produced, timeout=remaining(), cancel=job.cancel_event.is_set
                )
                problems = validate_output(probe, request.output)
                if problems:
                    raise OutputInvalidError(
                        "encoded output does not satisfy the media contract: " + "; ".join(problems)
                    )

            with timed(Stage.PUBLISH):
                published = dirs.publish(produced, OUTPUT_FILENAME)
                manifest = OutputManifest(
                    path=str(published),
                    content_hash=sha256_file(str(published)),
                    frame_accounting=accounting,
                    probe=probe,
                    settings_digest=job.record.settings_digest,
                    is_qualifying_evidence=False,
                    non_qualifying_reason=_non_qualifying_reason(profile),
                )

            memory = sampler.observe()
            logger.emit(
                "attempt.succeeded",
                output_path=str(published),
                delivery_frames=probe.counted_frames,
                duration_seconds=probe.duration_seconds,
                memory_status=memory.status.value,
                memory_peak_bytes=memory.peak_bytes,
            )
            self._finish(
                job,
                state=JobState.SUCCEEDED,
                stages=stages,
                output=manifest,
                memory=memory,
                frame_accounting_value=accounting,
                device_evidence=device_evidence,
                cleanup_survivor_groups=survivor_groups,
                notes=notes,
            )
            return

        except BaseException as exc:
            # Whatever the adapter observed before it failed is still evidence,
            # and a failed learned call is exactly when the device and argv
            # notes matter most. Copying them only on success left a failed
            # attempt asserting "no inference runtime" and
            # inference_device_status=not_applicable.
            if context is not None:
                if context.device_evidence is not None:
                    device_evidence = context.device_evidence
                notes.extend(context.notes)
            # Cleanup evidence rides on the exception, because a raised error
            # cannot return a capture result -- and timeout and cancellation are
            # exactly where a leaked process is most likely.
            leaked = tuple(getattr(exc, "survivors", ()))
            if leaked:
                survivor_groups.extend(leaked)
                notes.append(
                    f"process group(s) {list(leaked)} were still alive after "
                    "teardown; resource cleanup was not clean"
                )
            state, failure = self._classify(job, exc, dirs)
            memory = sampler.observe()
            logger.emit(
                "attempt.failed",
                state=state.value,
                failure_category=failure.category.value,
                error=failure.message,
                diagnostics_path=failure.diagnostics_path,
            )
            self._retain_diagnostics(dirs)
            self._finish(
                job,
                state=state,
                stages=stages,
                failure=failure,
                memory=memory,
                frame_accounting_value=None,
                device_evidence=device_evidence,
                cleanup_survivor_groups=survivor_groups,
                notes=notes,
            )
        finally:
            job.stage = None
            logger.close()

    def _classify(
        self, job: _Job, exc: BaseException, dirs: AttemptDirs
    ) -> tuple[JobState, FailureRecord]:
        diagnostics = str(dirs.diagnostics)
        if job.cancel_event.is_set() and not isinstance(exc, ValidationRejected):
            return JobState.CANCELLED, FailureRecord(
                category=FailureCategory.CANCELLED,
                message="job was cancelled before output was published",
                detail=str(exc),
                diagnostics_path=diagnostics,
            )
        if isinstance(exc, ValidationRejected):
            return JobState.FAILED, FailureRecord(
                category=FailureCategory.VALIDATION_REJECTED,
                message=str(exc),
                diagnostics_path=diagnostics,
                validation_codes=exc.codes,
            )
        if isinstance(exc, AnimaLiteError):
            return JobState.FAILED, FailureRecord(
                category=exc.category, message=str(exc), diagnostics_path=diagnostics
            )
        return JobState.FAILED, FailureRecord(
            category=FailureCategory.INTERNAL_ERROR,
            message=f"{type(exc).__name__}: {exc}",
            diagnostics_path=diagnostics,
        )

    @staticmethod
    def _retain_diagnostics(dirs: AttemptDirs) -> None:
        """Keep the scratch tree as diagnostics; never publish anything from it."""
        target = dirs.retain_diagnostics()
        if not dirs.work.is_dir():
            return
        for item in dirs.work.iterdir():
            destination = target / item.name
            if destination.exists():
                continue
            try:
                if item.is_dir():
                    shutil.copytree(item, destination)
                else:
                    # Partial encodes are retained as evidence with a name that
                    # cannot be mistaken for published output.
                    suffix = ".partial" if item.name == OUTPUT_FILENAME else ""
                    shutil.copy2(item, target / (item.name + suffix))
            except OSError:  # pragma: no cover - diagnostics are best effort
                continue

    @staticmethod
    def _check_cancelled(job: _Job) -> None:
        if job.cancel_event.is_set():
            raise JobCancelled("cancellation requested")

    def _decode_anchors(
        self,
        request: RenderRequest,
        budget_seconds: float,
        *,
        cancel: Callable[[], bool] | None = None,
        thread_budget: ThreadBudget | None = None,
    ) -> dict[int, NDArray[np.uint8]]:
        """Decode every anchor within the *job* deadline, not a private one.

        Each decode previously had its own 60 s timeout, so four anchors could
        consume four minutes regardless of the job's remaining budget.
        """
        frames: dict[int, NDArray[np.uint8]] = {}
        deadline = time.monotonic() + budget_seconds
        for anchor in request.anchors.anchors:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise JobTimeoutError(
                    "job deadline elapsed while decoding approved anchors "
                    f"({len(frames)} of {request.anchors.count} decoded)"
                )
            frames[anchor.animation_index] = decode_image_rgb24(
                self.tools,
                Path(anchor.asset.path),
                width=request.output.width,
                height=request.output.height,
                timeout=remaining,
                cancel=cancel,
                thread_budget=thread_budget,
            )
        return frames

    def _counted_frames(
        self,
        job: _Job,
        frames: Iterator[NDArray[np.uint8]],
        request: RenderRequest,
        synthesis_seconds: list[float] | None = None,
    ) -> Iterator[bytes]:
        """Adapt adapter output to encoder input, checking count and geometry.

        Yields raw bytes so nothing accumulates: the generator is consumed by
        the cadence expander, which is consumed by the encoder writer.
        """
        expected_shape = (request.output.height, request.output.width, 3)
        total = request.output.animation_frame_count
        produced = 0
        sink = synthesis_seconds if synthesis_seconds is not None else [0.0]
        while True:
            started = time.perf_counter()
            try:
                frame = next(frames)
            except StopIteration:
                break
            finally:
                # Every outcome, not only success: an inference that spent 0.3s
                # and then raised was charged to *encode*, because the elapsed
                # time was added after the call returned. A failure's cost
                # belongs to the stage that incurred it.
                sink[0] += time.perf_counter() - started
            self._check_cancelled(job)
            if frame.shape != expected_shape or frame.dtype != np.uint8:
                raise AdapterError(
                    f"adapter yielded frame {produced} with shape {frame.shape} dtype "
                    f"{frame.dtype}; expected {expected_shape} uint8"
                )
            produced += 1
            with job.lock:
                job.record = job.record.model_copy(
                    update={"progress": round(min(0.99, produced / total), 4)}
                )
            yield frame.tobytes()
        if produced != total:
            raise AdapterError(
                f"adapter yielded {produced} animation frames; the output contract requires {total}"
            )


def _non_qualifying_reason(profile: EngineProfile) -> str:
    """Why this artifact is not qualification evidence.

    A single render is never qualification evidence, but the *reason* differs
    and must be stated accurately. For a non-learned profile the profile itself
    is disqualifying. For a learned, qualification-eligible profile the profile
    is fine and the missing pieces are the protocol ones -- saying "no learned
    model is integrated" there would be false.
    """
    if not profile.qualification_eligible:
        return (
            profile.non_qualifying_reason
            or f"profile {profile.profile_id!r} is not qualification-eligible"
        )

    reasons = [
        f"profile {profile.profile_id!r} is qualification-eligible, but a single "
        "render is not qualification evidence: AT-055/AT-056 require the locked "
        "12-clip sample on the D-02-approved P-L host, complete warm/cold/preview "
        "distributions and two-reviewer quality evidence, evaluated together by "
        "`animalite benchmark`"
    ]
    evaluation = profile.license_evaluation
    if evaluation is not None and not evaluation.use_eligible:
        reasons.append(
            f"licence evaluation {evaluation.evaluation_id} is "
            f"{evaluation.policy_state!r} (use_eligible=False)"
        )
    return "; ".join(reasons)


class _StageTimer:
    """Context manager appending a :class:`StageTiming` on exit, success or not."""

    def __init__(self, stage: Stage, sink: list[StageTiming], logger: AttemptLogger) -> None:
        self.stage = stage
        self.sink = sink
        self.logger = logger
        self.start = 0.0

    def __enter__(self) -> _StageTimer:
        self.start = time.perf_counter()
        self.logger.emit("stage.start", stage=self.stage.value)
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        elapsed = time.perf_counter() - self.start
        self.sink.append(
            StageTiming(
                stage=self.stage,
                wall_seconds=round(elapsed, 6),
                inside_timing_boundary=self.stage is not Stage.RUNTIME_RESIDENCY,
                detail="incomplete" if exc_type is not None else None,
            )
        )
        self.logger.emit(
            "stage.end",
            stage=self.stage.value,
            duration_seconds=round(elapsed, 6),
            failed=exc_type is not None,
        )
