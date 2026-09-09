"""Request validation (MR-010: fail before expensive execution begins).

Every rule reports a stable code, a human message and a remediation hint
(section 11 API rules). Nothing here raises on invalid input: the caller gets a
:class:`~animalite.contracts.validation.ValidationReport` and decides.
"""

from __future__ import annotations

from pathlib import Path

from animalite.adapters.registry import Registry
from animalite.admission import evaluate_admission
from animalite.contracts.base import sha256_file
from animalite.contracts.enums import CadenceConversion, IssueSeverity
from animalite.contracts.job import RenderRequest
from animalite.contracts.profile import EngineProfile
from animalite.contracts.validation import ValidationIssue, ValidationReport
from animalite.errors import CodeVAL, ProfileNotFoundError
from animalite.media.ffmpeg import FFmpegTools

__all__ = ["validate_request"]


def _error(code: str, path: str, message: str, remediation: str) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        severity=IssueSeverity.ERROR,
        field_path=path,
        message=message,
        remediation=remediation,
    )


def _attribute_control_origin(
    issues: list[ValidationIssue], *, overridden: set[str]
) -> list[ValidationIssue]:
    """Re-point control issues at whichever side actually supplied the value.

    Adapters validate the resolved configuration and do not know where each
    value came from, so they all report ``controls.<name>``. When the request
    did not override that control the offending value is a *profile default*,
    and telling the caller to fix their request would be wrong. Origin is known
    in exactly one place -- here -- so the remap lives here rather than being
    reimplemented by every adapter.
    """
    remapped: list[ValidationIssue] = []
    for issue in issues:
        path = issue.field_path
        if not path.startswith("controls.") or path.split(".", 1)[1] in overridden:
            remapped.append(issue)
            continue
        name = path.split(".", 1)[1]
        remapped.append(
            issue.model_copy(
                update={
                    "field_path": f"engine_profile.parameters.{name}",
                    "remediation": (
                        f"{issue.remediation} This value is the {name!r} default of "
                        f"the engine profile, not a request control: correct the "
                        f"profile, or override {name!r} in the request."
                    ),
                }
            )
        )
    return remapped


def _validate_anchors(request: RenderRequest, profile: EngineProfile) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    anchors = request.anchors
    output = request.output

    count = anchors.count
    if not profile.min_anchor_count <= count <= profile.max_anchor_count:
        issues.append(
            _error(
                CodeVAL.PROFILE_ANCHOR_LIMIT,
                "anchors.anchors",
                f"{count} anchors supplied; profile {profile.profile_id!r} accepts "
                f"{profile.min_anchor_count}-{profile.max_anchor_count}",
                "Supply an anchor count within the profile's declared range. Section "
                "12.0 limits the quick-clip path to 2-4 approved frames.",
            )
        )

    if not anchors.endpoints_match(output):
        issues.append(
            _error(
                CodeVAL.ANCHOR_ENDPOINTS,
                "anchors.anchors",
                f"first/last anchors are at animation indices {anchors.indices[0]} and "
                f"{anchors.indices[-1]}; the output contract requires 0 and "
                f"{output.last_animation_index}",
                "Place the first anchor at animation index 0 and the last at "
                f"{output.last_animation_index}, or change animation_frame_count.",
            )
        )

    for anchor in anchors.anchors:
        field = f"anchors.anchors[{anchor.anchor_id}]"
        if anchor.animation_index >= output.animation_frame_count:
            issues.append(
                _error(
                    CodeVAL.ANCHOR_RANGE,
                    f"{field}.animation_index",
                    f"animation_index {anchor.animation_index} is outside the "
                    f"0..{output.last_animation_index} frame range",
                    "Re-index the anchor or increase animation_frame_count.",
                )
            )
        if not anchor.approved:
            issues.append(
                _error(
                    CodeVAL.ANCHOR_NOT_APPROVED,
                    f"{field}.approved",
                    "anchor is not marked approved",
                    "Only approved frames may be used as inputs (section 12.0).",
                )
            )
        if anchor.aspect_ratio != output.aspect_ratio:
            issues.append(
                _error(
                    CodeVAL.ANCHOR_ASPECT,
                    f"{field}",
                    f"anchor aspect ratio {anchor.aspect_ratio} != output aspect ratio "
                    f"{output.aspect_ratio} ({output.width}x{output.height})",
                    "Re-frame the anchor to the output aspect ratio; the pipeline "
                    "scales but never crops or letterboxes silently (NFR-019).",
                )
            )

        path = Path(anchor.asset.path)
        if not path.is_file():
            issues.append(
                _error(
                    CodeVAL.ANCHOR_MISSING_FILE,
                    f"{field}.asset.path",
                    f"anchor file does not exist: {path}",
                    "Resolve the asset before submitting, or re-run the fixture generator.",
                )
            )
            continue
        actual = sha256_file(str(path))
        if actual != anchor.asset.content_hash:
            issues.append(
                _error(
                    CodeVAL.ANCHOR_HASH_MISMATCH,
                    f"{field}.asset.content_hash",
                    f"content hash mismatch for {path}: declared "
                    f"{anchor.asset.content_hash}, found {actual}",
                    "The approved input changed on disk. Re-approve it or restore the "
                    "original; approved inputs are immutable (C-05).",
                )
            )
    return issues


def _validate_profile_fit(request: RenderRequest, profile: EngineProfile) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    output = request.output

    if request.shot.assigned_tier not in profile.supported_tiers:
        issues.append(
            _error(
                CodeVAL.PROFILE_TIER,
                "shot.assigned_tier",
                f"profile {profile.profile_id!r} does not support tier "
                f"{request.shot.assigned_tier.value}; supported: "
                f"{[t.value for t in profile.supported_tiers]}",
                "Route the shot to a supported tier or select another profile (CR-001).",
            )
        )
    if not profile.supports_resolution(output.width, output.height):
        supported = [f"{r.width}x{r.height}" for r in profile.supported_resolutions]
        issues.append(
            _error(
                CodeVAL.PROFILE_RESOLUTION,
                "output",
                f"profile {profile.profile_id!r} does not declare "
                f"{output.width}x{output.height}; declared: {supported}",
                "Use a declared resolution. Upscaled output is not native synthesis "
                "(section 12.0, 720p extension row).",
            )
        )
    if output.animation_frame_count > profile.max_animation_frame_count:
        issues.append(
            _error(
                CodeVAL.PROFILE_FRAME_COUNT,
                "output.animation_frame_count",
                f"{output.animation_frame_count} animation frames exceeds the profile "
                f"maximum {profile.max_animation_frame_count}",
                "Shorten the clip or select a profile with a larger declared range.",
            )
        )
    if request.shot.endpoint_control_mode not in profile.supported_endpoint_modes:
        issues.append(
            _error(
                CodeVAL.PROFILE_ENDPOINT_MODE,
                "shot.endpoint_control_mode",
                f"profile {profile.profile_id!r} does not declare endpoint mode "
                f"{request.shot.endpoint_control_mode.value}",
                "Declare a supported endpoint contract mode (MR-001, section 15.2).",
            )
        )
    for artifact in [*profile.weights, *profile.binaries]:
        if artifact.content_hash is None:
            issues.append(
                _error(
                    CodeVAL.PROFILE_ARTIFACT_UNVERIFIED,
                    f"profile.{artifact.kind}.{artifact.identifier}",
                    f"declared {artifact.kind} {artifact.identifier!r} has no verified "
                    "content hash",
                    "Pin and verify the binary/weight hash before use (handoff rule 7).",
                )
            )
    return issues


def _validate_admission(request: RenderRequest, profile: EngineProfile) -> list[ValidationIssue]:
    """Refuse a learned profile that has no approved admission record.

    An error, not a warning. The previous warning said development and
    benchmarking "may proceed", which meant a pending rights position blocked
    nothing that actually ran: the profile verified its digests and executed.
    Verification and admission are separate questions and this is the second
    one (CR-024, C-04, DEC-0013).
    """
    outcome = evaluate_admission(profile, request.execution_purpose)
    if outcome.admitted:
        return []
    code = {
        "missing": CodeVAL.ADMISSION_NOT_RECORDED,
        "artifacts_not_covered": CodeVAL.ADMISSION_SCOPE,
        "purpose_not_permitted": CodeVAL.ADMISSION_SCOPE,
    }.get(outcome.state, CodeVAL.ADMISSION_NOT_APPROVED)
    return [
        _error(
            code,
            "engine_profile_id",
            f"execution of learned profile {profile.profile_id!r} for purpose "
            f"{request.execution_purpose.value!r} is not admitted "
            f"({outcome.summary})",
            "Record the reviewed licence disposition for these exact artifacts "
            "and this purpose in the admission directory (see "
            "docs/licensing/admissions/README.md and DEC-0013). There is no "
            "development bypass: a pending decision blocks execution, not only "
            "qualification.",
        )
    ]


def _validate_media(request: RenderRequest) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    output = request.output
    if output.cadence.conversion is not CadenceConversion.DUPLICATE:
        issues.append(
            _error(
                CodeVAL.CADENCE_UNSUPPORTED,
                "output.cadence.conversion",
                f"cadence conversion {output.cadence.conversion.value!r} is not "
                "implemented; the project default is frame duplication",
                "Interpolated uplift needs a named owner, reason, downstream impact "
                "and a separately measured compute budget (CR-004, D-09).",
            )
        )
        # Delivery frame count and duration are only defined for hold-based
        # cadence, so the remaining media checks cannot be evaluated here.
        return issues

    declared = float(request.shot.target_duration_seconds)
    actual = float(output.duration_seconds)
    if abs(declared - actual) > 1e-9:
        issues.append(
            _error(
                CodeVAL.DURATION_MISMATCH,
                "shot.target_duration_seconds",
                f"shot targets {declared}s but the output contract encodes exactly "
                f"{actual}s ({output.delivery_frame_count} delivery frames at "
                f"{output.cadence.delivery_fps} fps)",
                "Align target_duration_seconds with animation_frame_count and cadence.",
            )
        )
    return issues


def validate_request(
    request: RenderRequest,
    registry: Registry,
    *,
    tools: FFmpegTools | None = None,
) -> ValidationReport:
    """Validate one render request against its profile, media contract and tooling."""
    issues: list[ValidationIssue] = []
    try:
        profile = registry.profile(request.engine_profile_id)
    except ProfileNotFoundError as exc:
        return ValidationReport(
            valid=False,
            request_id=request.request_id,
            profile_id=request.engine_profile_id,
            issues=[
                _error(
                    CodeVAL.PROFILE_UNKNOWN,
                    "engine_profile_id",
                    str(exc),
                    "Register the profile or pass one of the registered ids "
                    "(see `animalite profiles`).",
                )
            ],
        )

    issues.extend(_validate_anchors(request, profile))
    issues.extend(_validate_profile_fit(request, profile))
    issues.extend(_validate_media(request))
    issues.extend(_validate_admission(request, profile))
    # Validate the *effective* configuration -- profile defaults with the
    # request's overrides applied -- because that is what synthesis will read.
    # Validating `request.controls` alone let an invalid profile default reach
    # the adapter unchecked, and let a request control be accepted here and fail
    # mid-synthesis: `controls={"drift_pixels": "not-a-number"}` returned
    # valid=true with zero errors and then raised while converting to float.
    effective = profile.effective_controls(request.controls)
    issues.extend(
        _attribute_control_origin(
            registry.adapter_for(profile).validate(
                profile, request.anchors, request.output, effective
            ),
            overridden=set(request.controls),
        )
    )

    resolved_tools = tools if tools is not None else FFmpegTools.discover()
    if not resolved_tools.available:
        issues.append(
            _error(
                CodeVAL.TOOL_UNAVAILABLE,
                "environment.ffmpeg",
                f"FFmpeg tooling unavailable: {resolved_tools.unavailable_reason}",
                "Install FFmpeg providing ffmpeg and ffprobe, or set ANIMALITE_FFMPEG "
                "and ANIMALITE_FFPROBE. AnimaLite does not bundle FFmpeg.",
            )
        )

    return ValidationReport(
        valid=not any(i.severity is IssueSeverity.ERROR for i in issues),
        request_id=request.request_id,
        profile_id=profile.profile_id,
        issues=issues,
    )
