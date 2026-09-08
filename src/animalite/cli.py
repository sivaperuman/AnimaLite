"""AnimaLite command line interface.

The CLI is a thin shell over the same application operations the benchmark uses
(handoff rule 3). Machine-readable output goes to stdout; diagnostics go to
stderr, so ``animalite doctor --json | jq`` is always safe.

Commands
--------
``doctor``      host and tool inventory (inventory, never approval)
``profiles``    registered engine profiles and their qualification status
``capabilities`` the ``capabilities()`` result for one profile
``validate``    validate a render request without executing it
``estimate``    device-class-agnostic resource estimate
``render``      render one clip through the real CPU media path
``fixtures``    generate reproducible synthetic anchors / dataset manifests
``benchmark``   plan, run and report benchmark measurements
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from animalite import __version__
from animalite.adapters.registry import Registry, default_registry
from animalite.bench.evaluate import build_report
from animalite.bench.ledger import RunLedger
from animalite.bench.runner import BenchmarkRunner, build_plan, load_dataset, load_host_record
from animalite.contracts.assets import AnchorSet
from animalite.contracts.base import content_digest
from animalite.contracts.benchmark import (
    DatasetClip,
    DatasetManifest,
    EvidenceBundle,
    TargetSet,
)
from animalite.contracts.enums import JobState, QualificationVerdict
from animalite.contracts.job import RenderRequest
from animalite.contracts.media import P_L_FINAL_OUTPUT, PREVIEW_OUTPUT, OutputSpec
from animalite.contracts.shot import ShotIntent
from animalite.core.environment import capture_environment
from animalite.core.logging import StructuredLogger
from animalite.core.service import LocalExecutionService
from animalite.errors import AnimaLiteError, ValidationRejected
from animalite.fixtures.generator import FIXTURE_CLIPS, generate_clip, write_anchor_set
from animalite.hostinfo.inventory import collect_inventory
from animalite.media.ffmpeg import FFmpegTools

__all__ = ["build_parser", "main"]

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_INVALID = 2
EXIT_UNAVAILABLE = 3

NON_QUALIFYING_BANNER = (
    "NOTE: no learned temporal model is integrated in this package. Output from "
    "the fixture profile is not evidence for MR-018, AT-055 or AT-056."
)


def _emit(payload: Any, *, as_json: bool) -> None:
    if as_json:
        json.dump(payload, sys.stdout, indent=2, sort_keys=True, default=str)
        sys.stdout.write("\n")


def _note(message: str) -> None:
    print(message, file=sys.stderr)


# --------------------------------------------------------------------- commands


def cmd_doctor(args: argparse.Namespace) -> int:
    inventory = collect_inventory()
    if args.json:
        _emit(inventory.to_json_obj(), as_json=True)
    else:
        print(f"animalite {__version__}")
        print(
            f"host         : {inventory.os_name} {inventory.os_release} ({inventory.architecture})"
        )
        print(f"cpu          : {inventory.cpu_model}")
        print(
            f"cores        : {inventory.physical_cores} physical / "
            f"{inventory.logical_cores} logical"
        )
        print(f"simd         : {', '.join(inventory.cpu_flags_recorded) or 'not recorded'}")
        print(f"ram          : {inventory.total_ram_bytes} bytes")
        print(f"python       : {inventory.python_implementation} {inventory.python_version}")
        for tool in inventory.tools:
            state = tool.version or "" if tool.available else f"UNAVAILABLE ({tool.error})"
            flags = ", ".join(tool.license_relevant_flags) or "none recorded"
            print(f"{tool.name:<13}: {state} [license-relevant flags: {flags}]")
        print(
            f"memory method: {inventory.memory_measurement_method.value} "
            f"({inventory.memory_measurement_status.value}, scope "
            f"{inventory.memory_measurement_scope})"
        )
        print(
            f"host approval: {'APPROVED' if inventory.approval.approved else 'NOT APPROVED'} "
            "- inventory only, never a D-02 decision"
        )
        for warning in inventory.warnings:
            print(f"warning      : {warning}")
    missing = [t.name for t in inventory.tools if not t.available]
    if missing:
        _note(f"required tooling unavailable: {', '.join(missing)}")
        return EXIT_UNAVAILABLE
    return EXIT_OK


def cmd_profiles(args: argparse.Namespace) -> int:
    registry = default_registry()
    rows = [
        {
            "profile_id": p.profile_id,
            "engine_class": p.engine_class.value,
            "learned_temporal_participation": p.learned_temporal_participation,
            "qualification_eligible": p.qualification_eligible,
            "non_qualifying_reason": p.non_qualifying_reason,
            "supported_tiers": [t.value for t in p.supported_tiers],
            "supported_resolutions": [f"{r.width}x{r.height}" for r in p.supported_resolutions],
        }
        for p in registry.profiles()
    ]
    if args.json:
        _emit(rows, as_json=True)
    else:
        for row in rows:
            print(f"{row['profile_id']}  [{row['engine_class']}]")
            print(f"  qualification eligible : {row['qualification_eligible']}")
            print(f"  learned temporal       : {row['learned_temporal_participation']}")
            print(
                f"  tiers / resolutions    : {row['supported_tiers']} "
                f"{row['supported_resolutions']}"
            )
            if row["non_qualifying_reason"]:
                print(f"  non-qualifying reason  : {row['non_qualifying_reason']}")
    return EXIT_OK


def cmd_capabilities(args: argparse.Namespace) -> int:
    service = _service(args)
    capabilities = service.capabilities(args.profile)
    _emit(capabilities.to_json_obj(), as_json=True)
    return EXIT_OK


def cmd_validate(args: argparse.Namespace) -> int:
    service = _service(args)
    request = _request(args)
    report = service.validate(request)
    if args.json:
        _emit(report.to_json_obj(), as_json=True)
    else:
        print(report.summary())
        for issue in report.issues:
            print(f"  [{issue.severity.value}] {issue.code} {issue.field_path}: {issue.message}")
            if issue.remediation:
                print(f"      -> {issue.remediation}")
    return EXIT_OK if report.valid else EXIT_INVALID


def cmd_estimate(args: argparse.Namespace) -> int:
    service = _service(args)
    estimate = service.estimate(_request(args))
    _emit(estimate.to_json_obj(), as_json=True)
    _note("estimate only: not a measurement and not evidence for any section 12.0 target")
    return EXIT_OK


def cmd_render(args: argparse.Namespace) -> int:
    service = _service(args)
    request = _request(args)
    record = service.render_blocking(request)
    if args.json:
        _emit(record.to_json_obj(), as_json=True)
    else:
        print(f"attempt   : {record.attempt_id}")
        print(f"state     : {record.state.value}")
        print(f"profile   : {record.profile.profile_id}")
        print(f"wall (s)  : {record.wall_seconds}")
        if record.output is not None:
            probe = record.output.probe
            counts = record.output.frame_accounting
            print(f"output    : {record.output.path}")
            print(f"hash      : {record.output.content_hash}")
            print(
                f"decoded   : {probe.width}x{probe.height} {probe.codec}/{probe.profile} "
                f"{probe.pixel_format} {probe.counted_frames} frames @ "
                f"{probe.avg_frame_rate} = {probe.duration_seconds}s"
            )
            print(
                f"frames    : source={counts.source_frame_count} "
                f"synthesized={counts.synthesized_frame_count} "
                f"duplicated={counts.duplicated_frame_count} "
                f"(animation={counts.animation_frame_count}, "
                f"delivery={counts.delivery_frame_count})"
            )
            print(f"qualifying: {record.output.is_qualifying_evidence}")
            print(f"            {record.output.non_qualifying_reason}")
        if record.failure is not None:
            print(f"failure   : [{record.failure.category.value}] {record.failure.message}")
            print(f"diagnostics: {record.failure.diagnostics_path}")
        print(
            f"memory    : {record.memory.status.value} "
            f"{record.memory.peak_bytes} bytes via {record.memory.method.value}"
        )
    _note(NON_QUALIFYING_BANNER)
    return EXIT_OK if record.state is JobState.SUCCEEDED else EXIT_ERROR


def cmd_fixtures_generate(args: argparse.Namespace) -> int:
    tools = FFmpegTools.discover()
    if not tools.available:
        _note(f"cannot generate fixtures: {tools.unavailable_reason}")
        return EXIT_UNAVAILABLE
    clip_ids = [args.clip] if args.clip else sorted(FIXTURE_CLIPS)
    out_dir = Path(args.out_dir)
    written: list[dict[str, Any]] = []
    clips: list[DatasetClip] = []
    for clip_id in clip_ids:
        clip = FIXTURE_CLIPS[clip_id]
        clip_dir = out_dir / clip_id
        anchor_set = generate_clip(
            clip, clip_dir, width=args.width, height=args.height, tools=tools
        )
        manifest_path = write_anchor_set(anchor_set, clip_dir / "anchors.json")
        written.append(
            {
                "clip_id": clip_id,
                "anchors": anchor_set.indices,
                "manifest": str(manifest_path),
                "hashes": [a.asset.content_hash for a in anchor_set.anchors],
            }
        )
        clips.append(
            DatasetClip(
                clip_id=clip_id,
                category="fixture",
                anchor_count=anchor_set.count,
                anchor_manifest_path=str(manifest_path),
                animation_frame_count=clip.animation_frame_count,
                intended_action=clip.description,
                anchor_hashes=[a.asset.content_hash for a in anchor_set.anchors],
            )
        )
    dataset = DatasetManifest(
        dataset_id="fixture-development",
        revision=1,
        purpose="development",
        locked=False,
        clips=clips,
        notes=[
            "Synthetic development fixtures. NOT the section 12.0 locked 12-clip "
            "qualification sample and not usable as qualification evidence.",
        ],
    )
    dataset_path = out_dir / "dataset.json"
    dataset_path.write_text(
        json.dumps(dataset.to_json_obj(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _emit({"clips": written, "dataset": str(dataset_path)}, as_json=True)
    _note("fixture artwork is test material, not benchmark evidence")
    return EXIT_OK


def cmd_benchmark_run(args: argparse.Namespace) -> int:
    registry = default_registry()
    dataset = load_dataset(Path(args.dataset))
    host = load_host_record(Path(args.host))
    profile = registry.profile(args.profile)
    ledger = RunLedger(Path(args.ledger))
    targets = _targets(args)

    plan = build_plan(
        dataset=dataset,
        host=host,
        profile_id=profile.profile_id,
        profile_digest=content_digest(profile),
        target_revision=targets.target_revision,
        order_seed=args.seed,
        warm_repetitions=args.warm_repetitions,
        cold_repetitions=args.cold_repetitions,
        preview_repetitions=args.preview_repetitions,
    )
    ledger.write_plan(plan)

    runner = BenchmarkRunner(
        dataset=dataset,
        host=host,
        profile_id=profile.profile_id,
        workspace=Path(args.workspace),
        ledger=ledger,
        registry=registry,
        logger=StructuredLogger(enabled=args.verbose),
        timeout_seconds=args.timeout,
    )
    runner.run(plan)

    report = build_report(
        plan=plan,
        dataset=dataset,
        host=host,
        profile=profile,
        targets=targets,
        ledger=ledger,
        evidence=_evidence(args),
        environment=capture_environment(profile.thread_budget),
    )
    _write_report(report, Path(args.ledger) / "report.json")
    _print_report(report, as_json=args.json)
    return EXIT_OK if report.verdict is not QualificationVerdict.QUALIFYING_FAIL else EXIT_ERROR


def cmd_benchmark_report(args: argparse.Namespace) -> int:
    registry = default_registry()
    ledger = RunLedger(Path(args.ledger))
    plan = ledger.read_plan()
    dataset = load_dataset(Path(args.dataset))
    host = load_host_record(Path(args.host))
    profile = registry.profile(plan.profile_id)
    report = build_report(
        plan=plan,
        dataset=dataset,
        host=host,
        profile=profile,
        targets=_targets(args),
        ledger=ledger,
        evidence=_evidence(args),
    )
    _write_report(report, Path(args.ledger) / "report.json")
    _print_report(report, as_json=args.json)
    return EXIT_OK


# ---------------------------------------------------------------------- helpers


def _write_report(report: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.to_json_obj(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _print_report(report: Any, *, as_json: bool) -> None:
    if as_json:
        _emit(report.to_json_obj(), as_json=True)
        return
    print(f"verdict : {report.verdict.value}")
    print(f"label   : {report.label}")
    print(f"host    : {report.host_id} (approved={report.host_approved})")
    print(
        f"profile : {report.profile_id} "
        f"(qualification_eligible={report.profile_qualification_eligible})"
    )
    print(f"ledger  : {report.ledger_digest} verified={report.ledger_verified}")
    for summary in report.distributions:
        print(
            f"  {summary.kind.value:<20} planned={summary.n_planned} "
            f"succeeded={summary.n_succeeded} failed={summary.n_failed} "
            f"missing={summary.n_missing} median={summary.median_seconds} "
            f"p95={summary.p95_seconds} (index {summary.p95_sorted_index}) "
            f"max={summary.maximum_seconds}"
        )
    blocking = report.blocking_findings
    print(f"blocking findings: {len(blocking)}")
    for finding in blocking:
        print(f"  - [{finding.code}] {finding.message}")
        if finding.requirement_refs:
            print(f"      refs: {', '.join(finding.requirement_refs)}")


def _targets(args: argparse.Namespace) -> TargetSet:
    path = getattr(args, "targets", None)
    if path:
        return TargetSet.model_validate_json(Path(path).read_text(encoding="utf-8"))
    return TargetSet()


def _evidence(args: argparse.Namespace) -> EvidenceBundle:
    path = getattr(args, "evidence", None)
    if path:
        return EvidenceBundle.model_validate_json(Path(path).read_text(encoding="utf-8"))
    return EvidenceBundle()


def _registry() -> Registry:
    return default_registry()


def _service(args: argparse.Namespace) -> LocalExecutionService:
    workspace = Path(getattr(args, "workspace", None) or "work/ws")
    return LocalExecutionService(
        workspace,
        registry=_registry(),
        logger=StructuredLogger(enabled=getattr(args, "verbose", False)),
    )


def _output_spec(args: argparse.Namespace) -> OutputSpec:
    if getattr(args, "preview", False):
        base = PREVIEW_OUTPUT
    else:
        base = P_L_FINAL_OUTPUT
    updates: dict[str, Any] = {}
    if getattr(args, "width", None):
        updates["width"] = args.width
    if getattr(args, "height", None):
        updates["height"] = args.height
    if getattr(args, "animation_frames", None):
        updates["animation_frame_count"] = args.animation_frames
    return base.model_copy(update=updates) if updates else base


def _request(args: argparse.Namespace) -> RenderRequest:
    # A serialized request round-trips exactly, which is what lets the benchmark
    # execute an identical job in a fresh process for process-cold timing.
    request_file = getattr(args, "request_file", None)
    if request_file:
        return RenderRequest.model_validate_json(Path(request_file).read_text(encoding="utf-8"))

    if not args.anchors:
        raise ValidationRejected("--anchors is required unless --request-file is given")
    anchors = AnchorSet.model_validate_json(Path(args.anchors).read_text(encoding="utf-8"))
    output = _output_spec(args)
    controls: dict[str, float | int | str | bool] = {}
    for item in getattr(args, "control", None) or []:
        key, _, raw = item.partition("=")
        controls[key] = _coerce(raw)
    return RenderRequest(
        request_id=args.request_id,
        shot=ShotIntent(
            shot_code=args.shot_code,
            target_duration_seconds=float(output.duration_seconds),
            motion_description=args.motion or "",
        ),
        anchors=anchors,
        engine_profile_id=args.profile,
        output=output,
        controls=controls,
        timeout_seconds=args.timeout,
        parent_attempt_id=getattr(args, "retry_of", None),
    )


def _coerce(raw: str) -> float | int | str | bool:
    lowered = raw.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw


def _add_request_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--profile",
        required=True,
        help="engine profile id (required: rendering never selects an engine implicitly)",
    )
    parser.add_argument("--anchors", default=None, help="path to an anchor-set JSON file")
    parser.add_argument(
        "--request-file",
        default=None,
        help=(
            "execute a serialized RenderRequest verbatim. Used by the benchmark's "
            "process-cold path so the child runs an identical job."
        ),
    )
    parser.add_argument("--request-id", default="cli-request", help="request identifier")
    parser.add_argument(
        "--shot-code", default="CLI-SHOT", help="shot code recorded in the manifest"
    )
    parser.add_argument(
        "--motion", default=None, help="motion description recorded in the shot intent"
    )
    parser.add_argument("--workspace", default="work/ws", help="attempt workspace directory")
    parser.add_argument(
        "--preview", action="store_true", help="use the 320x180 3-second preview spec"
    )
    parser.add_argument("--width", type=int, default=None, help="override output width")
    parser.add_argument("--height", type=int, default=None, help="override output height")
    parser.add_argument(
        "--animation-frames", type=int, default=None, help="override animation frame count"
    )
    parser.add_argument(
        "--control",
        action="append",
        metavar="NAME=VALUE",
        help="adapter control; an unsupported control is reported, never ignored",
    )
    parser.add_argument(
        "--timeout", type=float, default=600.0, help="finite job deadline in seconds"
    )
    parser.add_argument("--json", action="store_true", help="emit JSON on stdout")
    parser.add_argument("--verbose", action="store_true", help="stream structured logs to stderr")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="animalite",
        description=(
            "AnimaLite CPU execution foundation and benchmark harness. "
            "No learned temporal model is integrated; no section 12.0 target has "
            "been measured or met."
        ),
    )
    parser.add_argument("--version", action="version", version=f"animalite {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="report host and tool inventory")
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(func=cmd_doctor)

    profiles = sub.add_parser("profiles", help="list registered engine profiles")
    profiles.add_argument("--json", action="store_true")
    profiles.set_defaults(func=cmd_profiles)

    capabilities = sub.add_parser("capabilities", help="report capabilities() for a profile")
    capabilities.add_argument("--profile", required=True)
    capabilities.add_argument("--workspace", default="work/ws")
    capabilities.set_defaults(func=cmd_capabilities)

    validate = sub.add_parser("validate", help="validate a render request without executing")
    _add_request_arguments(validate)
    validate.set_defaults(func=cmd_validate)

    estimate = sub.add_parser("estimate", help="report a device-class-agnostic resource estimate")
    _add_request_arguments(estimate)
    estimate.set_defaults(func=cmd_estimate)

    render = sub.add_parser("render", help="render one clip through the real CPU media path")
    _add_request_arguments(render)
    render.add_argument(
        "--retry-of", default=None, help="parent attempt id; a retry creates a new attempt"
    )
    render.set_defaults(func=cmd_render)

    fixtures = sub.add_parser("fixtures", help="reproducible synthetic fixtures")
    fixtures_sub = fixtures.add_subparsers(dest="fixtures_command", required=True)
    generate = fixtures_sub.add_parser("generate", help="generate synthetic anchors and a manifest")
    generate.add_argument("--out-dir", required=True)
    generate.add_argument("--clip", choices=sorted(FIXTURE_CLIPS), default=None)
    generate.add_argument("--width", type=int, default=640)
    generate.add_argument("--height", type=int, default=360)
    generate.set_defaults(func=cmd_fixtures_generate)

    benchmark = sub.add_parser("benchmark", help="plan, run and report benchmark measurements")
    benchmark_sub = benchmark.add_subparsers(dest="benchmark_command", required=True)

    bench_run = benchmark_sub.add_parser("run", help="execute a benchmark plan")
    bench_run.add_argument("--dataset", required=True)
    bench_run.add_argument("--host", required=True, help="host record JSON (see benchmarks/hosts/)")
    bench_run.add_argument("--profile", required=True)
    bench_run.add_argument("--ledger", required=True, help="ledger directory (created if absent)")
    bench_run.add_argument("--workspace", default="work/bench")
    bench_run.add_argument("--targets", default=None, help="target set JSON; defaults to proposed")
    bench_run.add_argument("--evidence", default=None, help="evidence bundle JSON")
    bench_run.add_argument(
        "--seed", type=int, default=1, help="run-order seed, recorded in the plan"
    )
    bench_run.add_argument("--warm-repetitions", type=int, default=3)
    bench_run.add_argument("--cold-repetitions", type=int, default=1)
    bench_run.add_argument("--preview-repetitions", type=int, default=3)
    bench_run.add_argument("--timeout", type=float, default=600.0)
    bench_run.add_argument("--json", action="store_true")
    bench_run.add_argument("--verbose", action="store_true")
    bench_run.set_defaults(func=cmd_benchmark_run)

    bench_report = benchmark_sub.add_parser("report", help="re-evaluate an existing ledger")
    bench_report.add_argument("--ledger", required=True)
    bench_report.add_argument("--dataset", required=True)
    bench_report.add_argument("--host", required=True)
    bench_report.add_argument("--targets", default=None)
    bench_report.add_argument("--evidence", default=None)
    bench_report.add_argument("--json", action="store_true")
    bench_report.set_defaults(func=cmd_benchmark_report)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.func(args)
        return int(result)
    except AnimaLiteError as exc:
        _note(f"error: {type(exc).__name__}: {exc}")
        return EXIT_ERROR
    except FileNotFoundError as exc:
        _note(f"error: file not found: {exc}")
        return EXIT_ERROR
    except KeyboardInterrupt:  # pragma: no cover - interactive
        _note("interrupted")
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
