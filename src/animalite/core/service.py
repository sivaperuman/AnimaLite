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
from collections.abc import Iterator
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
from animalite.contracts.profile import Capabilities, EngineProfile
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
from animalite.core.resources import MemorySampler
from animalite.core.validation import validate_request
from animalite.errors import (
    AdapterError,
    AnimaLiteError,
    OutputInvalidError,
    ValidationRejected,
)
from animalite.media.cadence import expand_to_delivery, frame_accounting
from animalite.media.decode import decode_image_rgb24
from animalite.media.encode import encode_delivery_stream
from animalite.media.ffmpeg import FFmpegTools
from animalite.media.probe import probe_output, validate_output

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
        sampler = MemorySampler()
        logger = AttemptLogger(job.record.attempt_id, dirs.log_path, console=self._logger)
        device_evidence = DeviceEvidence(
            inference_device_status=EvidenceStatus.NOT_APPLICABLE,
            inference_device=None,
            encoder_device="cpu",
            hardware_acceleration_requested=False,
            network_calls_observed_status=EvidenceStatus.PENDING,
            notes=[
                "Package A runs no inference runtime, so there is no CPU-only "
                "inference claim to evidence here (MR-015 remains open).",
                "The encoder is invoked with software codecs only; no hardware "
                "acceleration flag is passed.",
                "Network isolation is not asserted by this package; AT-056's offline "
                "rerun is a Package C activity.",
            ],
        )
        deadline = time.monotonic() + request.timeout_seconds

        def remaining() -> float:
            return max(0.1, deadline - time.monotonic())

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

            with timed(Stage.DECODE_ANCHORS):
                anchor_frames = self._decode_anchors(request)

            self._check_cancelled(job)
            accounting = frame_accounting(request.anchors, request.output)

            produced = dirs.work / OUTPUT_FILENAME
            encoder_stderr = dirs.work / "encoder.stderr.log"

            with timed(Stage.TEMPORAL_SYNTHESIS):
                context = AdapterContext(
                    anchor_frames=anchor_frames,
                    output=request.output,
                    anchors=request.anchors,
                    profile=profile,
                    cancel_requested=job.cancel_event,
                )
                frames = self._counted_frames(job, adapter.synthesize(context), request)

            with timed(Stage.ENCODE):
                encode_delivery_stream(
                    self.tools,
                    expand_to_delivery(frames, request.output),
                    request.output,
                    produced,
                    thread_budget=profile.thread_budget,
                    timeout_seconds=remaining(),
                    stderr_path=encoder_stderr,
                )

            self._check_cancelled(job)

            with timed(Stage.VALIDATE_OUTPUT):
                probe = probe_output(self.tools, produced, timeout=remaining())
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
                    non_qualifying_reason=(
                        profile.non_qualifying_reason
                        or "no learned temporal model is integrated in this package"
                    ),
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
            )
            return

        except BaseException as exc:
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
            raise AdapterError("cancellation requested")

    def _decode_anchors(self, request: RenderRequest) -> dict[int, NDArray[np.uint8]]:
        frames: dict[int, NDArray[np.uint8]] = {}
        for anchor in request.anchors.anchors:
            frames[anchor.animation_index] = decode_image_rgb24(
                self.tools,
                Path(anchor.asset.path),
                width=request.output.width,
                height=request.output.height,
            )
        return frames

    def _counted_frames(
        self,
        job: _Job,
        frames: Iterator[NDArray[np.uint8]],
        request: RenderRequest,
    ) -> Iterator[bytes]:
        """Adapt adapter output to encoder input, checking count and geometry.

        Yields raw bytes so nothing accumulates: the generator is consumed by
        the cadence expander, which is consumed by the encoder writer.
        """
        expected_shape = (request.output.height, request.output.width, 3)
        total = request.output.animation_frame_count
        produced = 0
        for frame in frames:
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
