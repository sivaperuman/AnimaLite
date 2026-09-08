"""Benchmark runner.

The runner drives :class:`~animalite.core.service.LocalExecutionService` -- the
same code path the CLI uses. There is no benchmark-only render path, so a harness
result and a CLI result come from identical execution (handoff rule 3).

Timing boundaries follow section 12.0:

* **warm** -- the clock starts at submission of a valid job with approved inputs
  already installed and stops when the encoded file is closed and decodable.
  Everything job-specific is inside: anchor decode, synthesis, cadence expansion,
  normalization, encode and the decode validation that proves the file is
  playable.
* **process-cold** -- the clock starts before a **new interpreter process** is
  launched, so Python startup, imports, tool discovery, service construction,
  adapter construction and any future model load are all inside the boundary.
  Reconstructing the service in the *same* interpreter is not process-cold:
  imports, native initialisation and any resident adapter state are already
  warm. Each cold run therefore executes `python -m animalite render` as a fresh
  child and records its pid and start marker as evidence. OS file-cache state is
  *not* cleared, and the record says so: this is process-cold, never disk-cold.
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from animalite.adapters.registry import Registry, default_registry
from animalite.bench.ledger import RunLedger
from animalite.contracts.assets import AnchorSet
from animalite.contracts.base import content_digest
from animalite.contracts.benchmark import (
    BenchmarkPlan,
    ColdProcessEvidence,
    DatasetClip,
    DatasetManifest,
    HostRecord,
    PlannedRun,
    RunRecord,
)
from animalite.contracts.enums import FailureCategory, JobState, RunKind, RunOutcome
from animalite.contracts.job import (
    AttemptRecord,
    EnvironmentRecord,
    ExecutionEnvelope,
    FailureRecord,
    ProcessInstance,
    RenderRequest,
)
from animalite.contracts.media import P_L_FINAL_OUTPUT, PREVIEW_OUTPUT, OutputSpec
from animalite.contracts.profile import EngineProfile
from animalite.contracts.shot import ShotIntent
from animalite.core.environment import capture_environment, current_process_instance
from animalite.core.logging import StructuredLogger, utc_now
from animalite.core.service import LocalExecutionService
from animalite.media.ffmpeg import FFmpegTools
from animalite.proc import CaptureResult, run_capture

#: Bounded teardown grace added on top of the job deadline for the cold child.
#: The child enforces its own job deadline; this covers only interpreter
#: shutdown and process-group teardown, so a hung child cannot outlive the plan.
COLD_TEARDOWN_GRACE_SECONDS = 30.0

__all__ = [
    "COLD_TEARDOWN_GRACE_SECONDS",
    "BenchmarkRunner",
    "build_plan",
    "load_dataset",
    "load_host_record",
    # Re-exported so tests can substitute the supervised launcher at this
    # module's boundary rather than reaching into `animalite.proc` globally.
    "run_capture",
]


def load_dataset(path: Path) -> DatasetManifest:
    return DatasetManifest.model_validate_json(Path(path).read_text(encoding="utf-8"))


def load_host_record(path: Path) -> HostRecord:
    return HostRecord.model_validate_json(Path(path).read_text(encoding="utf-8"))


def build_plan(
    *,
    dataset: DatasetManifest,
    host: HostRecord,
    profile_id: str,
    profile_digest: str,
    target_revision: str,
    order_seed: int,
    warm_repetitions: int = 3,
    cold_repetitions: int = 1,
    preview_repetitions: int = 3,
    plan_id: str | None = None,
) -> BenchmarkPlan:
    """Build the full run schedule in a fixed, seeded random order.

    Section 12.0 requires a fixed randomized order at batch size one. The seed is
    recorded in the plan so the same order can be replayed.
    """
    runs: list[PlannedRun] = []
    for clip in dataset.clips:
        for kind, repetitions in (
            (RunKind.WARM_FINAL, warm_repetitions),
            (RunKind.COLD_FINAL, cold_repetitions),
            (RunKind.WARM_PREVIEW, preview_repetitions),
        ):
            for repetition in range(1, repetitions + 1):
                runs.append(
                    PlannedRun(
                        run_id=f"{clip.clip_id}:{kind.value}:{repetition}",
                        clip_id=clip.clip_id,
                        kind=kind,
                        repetition=repetition,
                        order_index=0,
                    )
                )
    # Not cryptographic: section 12.0 wants a *fixed randomized order*, and the
    # seed is recorded in the plan so the order can be replayed exactly.
    random.Random(order_seed).shuffle(runs)  # noqa: S311
    ordered = [run.model_copy(update={"order_index": index}) for index, run in enumerate(runs)]

    return BenchmarkPlan(
        plan_id=plan_id or f"plan-{time.strftime('%Y%m%dT%H%M%S', time.gmtime())}",
        created_at=utc_now(),
        dataset_id=dataset.dataset_id,
        dataset_digest=content_digest(dataset),
        host_id=host.host_id,
        profile_id=profile_id,
        profile_digest=profile_digest,
        target_revision=target_revision,
        order_seed=order_seed,
        batch_size=1,
        warm_repetitions_per_clip=warm_repetitions,
        cold_repetitions_per_clip=cold_repetitions,
        preview_repetitions_per_clip=preview_repetitions,
        planned_runs=ordered,
        notes=[
            "Warm runs reuse only application/runtime residency; no cached final "
            "frames or precomputed job features carry over.",
            "Process-cold runs launch a fresh interpreter INSIDE the clock, so "
            "Python startup, imports, tool discovery and service/adapter "
            "construction are all inside the boundary. The OS file cache is NOT "
            "cleared; this is process-cold, not disk-cold.",
            "Preview repetitions: 36 independent warm preview requests, three per "
            "clip, recorded as a measurement clarification (DEC-0006).",
        ],
    )


class BenchmarkRunner:
    """Executes a plan and appends one ledger record per planned run."""

    def __init__(
        self,
        *,
        dataset: DatasetManifest,
        host: HostRecord,
        profile_id: str,
        workspace: Path,
        ledger: RunLedger,
        registry: Registry | None = None,
        tools: FFmpegTools | None = None,
        logger: StructuredLogger | None = None,
        final_output: OutputSpec = P_L_FINAL_OUTPUT,
        preview_output: OutputSpec = PREVIEW_OUTPUT,
        timeout_seconds: float = 600.0,
    ) -> None:
        self.dataset = dataset
        self.host = host
        self.profile_id = profile_id
        self.workspace = Path(workspace)
        self.ledger = ledger
        self.registry = registry if registry is not None else default_registry()
        self.tools = tools if tools is not None else FFmpegTools.discover()
        self.logger = logger if logger is not None else StructuredLogger(enabled=False)
        self.final_output = final_output
        self.preview_output = preview_output
        self.timeout_seconds = timeout_seconds
        self._clips = {clip.clip_id: clip for clip in dataset.clips}
        self._anchor_cache: dict[str, AnchorSet] = {}
        self._warm_service: LocalExecutionService | None = None

    # ------------------------------------------------------------------ execution

    def run(
        self, plan: BenchmarkPlan, *, runs: Sequence[PlannedRun] | None = None
    ) -> list[RunRecord]:
        """Execute the plan in its recorded order, appending every outcome."""
        selected = list(runs if runs is not None else plan.planned_runs)
        selected.sort(key=lambda r: r.order_index)
        records: list[RunRecord] = []
        for planned in selected:
            try:
                record = self.run_one(plan, planned)
            except Exception as exc:
                # One run's failure must not lose the record for that run *or*
                # abandon the rest of the plan. An unhandled TimeoutExpired at
                # the cold launch boundary previously aborted run() with zero of
                # two planned runs appended.
                record = self._not_run(
                    plan,
                    planned,
                    f"run failed at the harness boundary: {type(exc).__name__}: {exc}",
                    outcome=RunOutcome.FAILED,
                )
            self.ledger.append(record)
            records.append(record)
        return records

    def run_one(self, plan: BenchmarkPlan, planned: PlannedRun) -> RunRecord:
        """Execute one planned run and return its record -- success or failure."""
        clip = self._clips.get(planned.clip_id)
        if clip is None:
            return self._not_run(
                plan,
                planned,
                f"clip {planned.clip_id!r} is not in dataset {self.dataset.dataset_id!r}",
            )

        started_at = utc_now()
        profile = self.registry.profile(self.profile_id)
        try:
            anchors = self._anchors(clip)
        except (OSError, ValueError) as exc:
            return self._not_run(plan, planned, f"anchor set unavailable: {exc}")

        preview = planned.kind is RunKind.WARM_PREVIEW
        output = self.preview_output if preview else self.final_output
        request = RenderRequest(
            request_id=f"{plan.plan_id}:{planned.run_id}",
            shot=ShotIntent(
                shot_code=clip.clip_id,
                target_duration_seconds=float(output.duration_seconds),
                motion_description=clip.intended_action,
            ),
            anchors=self._fit_anchors(anchors, output),
            engine_profile_id=self.profile_id,
            output=output,
            timeout_seconds=self.timeout_seconds,
            label=f"{planned.kind.value}#{planned.repetition}",
        )

        if planned.kind is RunKind.COLD_FINAL:
            return self._run_cold(plan, planned, request, started_at, profile)

        service = self._warm(plan)
        clock_start = time.perf_counter()
        attempt = service.render_blocking(request)
        wall_seconds = time.perf_counter() - clock_start
        return self._record_from_attempt(plan, planned, attempt, wall_seconds, started_at, profile)

    def _run_cold(
        self,
        plan: BenchmarkPlan,
        planned: PlannedRun,
        request: RenderRequest,
        started_at: str,
        profile: EngineProfile,
    ) -> RunRecord:
        """Execute one process-cold run in a genuinely fresh interpreter.

        The clock starts *before* the child is launched, so interpreter startup,
        imports, tool discovery and service/adapter construction are all inside
        the section 12.0 cold boundary.

        The child receives an :class:`ExecutionEnvelope` -- request *and*
        resolved profile with its digest -- not a bare profile id. Passing the
        id alone let the child rebuild its own default registry: with an
        overridden ``fixture-synthetic`` in the parent, the warm run produced
        one output and the cold run produced the *default* profile's output,
        while both recorded success under the same planned profile.
        """
        run_dir = self.workspace / "cold" / planned.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        marker_path = run_dir / "process.json"
        marker_path.unlink(missing_ok=True)
        envelope = ExecutionEnvelope(
            envelope_id=f"{plan.plan_id}:{planned.run_id}",
            request=request,
            profile=profile,
            profile_digest=content_digest(profile),
            process_marker_path=str(marker_path),
        )
        envelope_path = run_dir / "envelope.json"
        envelope_path.write_text(
            json.dumps(envelope.to_json_obj(), indent=2, sort_keys=True), encoding="utf-8"
        )

        argv = [
            sys.executable,
            "-m",
            "animalite",
            "render",
            "--envelope",
            str(envelope_path),
            "--workspace",
            str(run_dir / "ws"),
            "--json",
        ]
        # One launch-to-completion deadline. The child enforces the job deadline
        # itself; the parent's allowance adds only the bounded teardown grace,
        # so a hung child cannot outlive the plan.
        supervision_seconds = self.timeout_seconds + COLD_TEARDOWN_GRACE_SECONDS
        clock_start = time.perf_counter()
        try:
            completed = run_capture(
                argv,
                timeout=supervision_seconds,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                grace_seconds=COLD_TEARDOWN_GRACE_SECONDS,
            )
        except TimeoutError as exc:
            wall_seconds = time.perf_counter() - clock_start
            return self._not_run(
                plan,
                planned,
                f"process-cold child exceeded the {supervision_seconds:.1f}s "
                f"launch-to-completion deadline and its process group was torn "
                f"down after {wall_seconds:.3f}s: {exc}",
                outcome=RunOutcome.TIMEOUT,
                category=FailureCategory.TIMEOUT,
                failure_seconds=wall_seconds,
            )
        except (OSError, ValueError) as exc:
            # Launch failure: no interpreter, unreadable envelope, bad argv.
            wall_seconds = time.perf_counter() - clock_start
            return self._not_run(
                plan,
                planned,
                f"process-cold child could not be launched: {type(exc).__name__}: {exc}",
                outcome=RunOutcome.FAILED,
                failure_seconds=wall_seconds,
            )
        wall_seconds = time.perf_counter() - clock_start

        evidence = self._cold_evidence(completed, argv, marker_path)
        stdout = completed.stdout.decode("utf-8", "replace")
        stderr = completed.stderr.decode("utf-8", "replace")

        # Parse the child's record *before* judging its exit status. A child
        # that timed out cleanly exits 1 while writing a complete failed
        # AttemptRecord; rejecting it on the exit code alone discarded the
        # attempt id, the timeout category and the retained diagnostics.
        attempt = self._parse_child_record(stdout)
        if attempt is None:
            return self._not_run(
                plan,
                planned,
                f"process-cold child exited {completed.returncode} without a valid "
                f"attempt record: {stderr.strip()[-500:]}",
                outcome=(RunOutcome.FAILED if completed.returncode != 0 else RunOutcome.NOT_RUN),
                cold_process_evidence=evidence,
                failure_seconds=wall_seconds,
            )

        succeeded = attempt.state is JobState.SUCCEEDED
        if succeeded != (completed.returncode == 0):
            # Success JSON with a failing exit status (or the reverse) means the
            # child and its process status disagree. That is a protocol error,
            # not a success: accepting the JSON would let a broken child report
            # a pass it never achieved.
            return self._not_run(
                plan,
                planned,
                f"process-cold child reported state {attempt.state.value!r} but exited "
                f"{completed.returncode}; refusing to accept a record that contradicts "
                "the process status",
                outcome=RunOutcome.FAILED,
                cold_process_evidence=evidence,
                failure_seconds=wall_seconds,
            )

        executed_digest = content_digest(attempt.profile)
        if executed_digest != envelope.profile_digest:
            return self._not_run(
                plan,
                planned,
                f"process-cold child executed profile digest {executed_digest} but the "
                f"plan scheduled {envelope.profile_digest}; the child ran different "
                "settings than were planned",
                outcome=RunOutcome.FAILED,
                cold_process_evidence=evidence,
                failure_seconds=wall_seconds,
            )

        record = self._record_from_attempt(
            plan, planned, attempt, wall_seconds, started_at, profile
        )
        return record.model_copy(update={"cold_process_evidence": evidence})

    def _cold_evidence(
        self, completed: CaptureResult, argv: list[str], marker_path: Path
    ) -> ColdProcessEvidence:
        """Build the evidence that this run really used a new process instance.

        The pid comes from the launched process handle -- ``CompletedProcess``
        has no ``pid`` attribute at all, so the previous ``hasattr`` fallback
        silently recorded ``None`` every time. The child's own start marker adds
        boot id and start time, which is what makes two cold runs provably
        distinct instances rather than merely distinct pids.
        """
        child_instance: ProcessInstance | None = None
        try:
            child_instance = ProcessInstance.model_validate_json(
                marker_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            child_instance = None
        return ColdProcessEvidence(
            child_pid=completed.pid,
            parent_pid=os.getpid(),
            interpreter=sys.executable,
            argv=argv,
            os_file_cache_cleared=False,
            child_instance=child_instance,
            parent_instance=current_process_instance(),
            child_survivor_groups=list(completed.survivors),
        )

    @staticmethod
    def _parse_child_record(stdout: str) -> AttemptRecord | None:
        """Recover the child's attempt record from stdout, or ``None``.

        Non-JSON notes may share stdout, so the record is taken from the last
        parseable JSON object rather than assuming the whole stream is one.
        """
        text = stdout.strip()
        if not text:
            return None
        candidates = [text]
        start = text.find("{")
        if start > 0:
            candidates.append(text[start:])
        for candidate in candidates:
            try:
                return AttemptRecord.model_validate_json(candidate)
            except ValueError:
                continue
        return None

    # ------------------------------------------------------------------ internals

    def _warm(self, plan: BenchmarkPlan) -> LocalExecutionService:
        if self._warm_service is None:
            self._warm_service = LocalExecutionService(
                self.workspace / "warm",
                registry=self.registry,
                tools=self.tools,
                logger=self.logger,
            )
        return self._warm_service

    def _anchors(self, clip: DatasetClip) -> AnchorSet:
        cached = self._anchor_cache.get(clip.clip_id)
        if cached is not None:
            return cached
        payload = json.loads(Path(clip.anchor_manifest_path).read_text(encoding="utf-8"))
        anchors = AnchorSet.model_validate(payload)
        self._anchor_cache[clip.clip_id] = anchors
        return anchors

    @staticmethod
    def _fit_anchors(anchors: AnchorSet, output: OutputSpec) -> AnchorSet:
        """Re-index the last anchor when a preview uses a shorter animation stream.

        Only the endpoint index changes; the approved image content and its hash
        are untouched, and a preview whose anchors cannot be re-indexed onto the
        preview stream fails validation rather than being silently reshaped.
        """
        if anchors.indices[-1] == output.last_animation_index:
            return anchors
        scale = output.last_animation_index / anchors.indices[-1]
        updated = []
        for position, anchor in enumerate(anchors.anchors):
            if position == 0:
                new_index = 0
            elif position == len(anchors.anchors) - 1:
                new_index = output.last_animation_index
            else:
                scaled = round(anchor.animation_index * scale)
                new_index = max(1, min(output.last_animation_index - 1, scaled))
            updated.append(anchor.model_copy(update={"animation_index": new_index}))
        return AnchorSet(anchors=updated)

    def _not_run(
        self,
        plan: BenchmarkPlan,
        planned: PlannedRun,
        reason: str,
        outcome: RunOutcome = RunOutcome.NOT_RUN,
        *,
        category: FailureCategory = FailureCategory.INTERNAL_ERROR,
        cold_process_evidence: ColdProcessEvidence | None = None,
        failure_seconds: float | None = None,
    ) -> RunRecord:
        """Record a run that never produced an acceptable service attempt.

        Section 12.0 keeps every attempted run: a setup failure appends a record
        and the plan continues, rather than silently losing the remainder.

        ``failure_seconds`` is recorded separately from the timing fields on
        purpose. How long a failure took is diagnostic information; folding it
        into ``wall_seconds`` would let a failure's latency enter the measured
        sample as if it were an observation.
        """
        return RunRecord(
            run_id=planned.run_id,
            plan_id=plan.plan_id,
            clip_id=planned.clip_id,
            kind=planned.kind,
            repetition=planned.repetition,
            outcome=outcome,
            failure=FailureRecord(category=category, message=reason),
            host_id=self.host.host_id,
            profile_id=self.profile_id,
            qualification_eligible_profile=False,
            exploratory=True,
            cold_process_evidence=cold_process_evidence,
            failure_elapsed_seconds=failure_seconds,
        )

    def _record_from_attempt(
        self,
        plan: BenchmarkPlan,
        planned: PlannedRun,
        attempt: AttemptRecord,
        wall_seconds: float,
        started_at: str,
        profile: EngineProfile,
    ) -> RunRecord:
        eligible = profile.qualification_eligible
        exploratory = not (eligible and self.host.approval.approved)

        if attempt.state is JobState.SUCCEEDED and attempt.output is not None:
            outcome = RunOutcome.SUCCEEDED
            recorded_wall: float | None = round(wall_seconds, 6)
            output_hash: str | None = attempt.output.content_hash
            failure_elapsed: float | None = None
        else:
            outcome = self._failure_outcome(attempt)
            recorded_wall = None
            output_hash = None
            # Kept, but in its own field: how long a failure took is diagnostic,
            # and must not enter the latency sample as an observation.
            failure_elapsed = round(wall_seconds, 6)

        return RunRecord(
            run_id=planned.run_id,
            plan_id=plan.plan_id,
            clip_id=planned.clip_id,
            kind=planned.kind,
            repetition=planned.repetition,
            outcome=outcome,
            attempt_id=attempt.attempt_id,
            started_at=started_at,
            finished_at=utc_now(),
            wall_seconds=recorded_wall,
            stages=list(attempt.stages),
            frame_accounting=attempt.frame_accounting,
            memory=attempt.memory,
            output_hash=output_hash,
            failure=attempt.failure,
            environment=attempt.environment or self._fallback_environment(),
            host_id=self.host.host_id,
            profile_id=self.profile_id,
            qualification_eligible_profile=eligible,
            exploratory=exploratory,
            failure_elapsed_seconds=failure_elapsed,
        )

    def _fallback_environment(self) -> EnvironmentRecord:
        budget = self.registry.profile(self.profile_id).thread_budget
        return capture_environment(budget, self.tools)

    @staticmethod
    def _failure_outcome(attempt: AttemptRecord) -> RunOutcome:
        from animalite.contracts.enums import FailureCategory

        if attempt.failure is None:
            return RunOutcome.FAILED
        if attempt.failure.category is FailureCategory.TIMEOUT:
            return RunOutcome.TIMEOUT
        if attempt.failure.category is FailureCategory.OUTPUT_INVALID:
            return RunOutcome.INVALID_OUTPUT
        return RunOutcome.FAILED
