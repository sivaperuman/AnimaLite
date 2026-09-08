"""Host and environment inventory.

Handoff section 13, item 5: this is *inventory*. It is not owner approval, and
it is not proof that an accelerated device was unused. Unknown values are
recorded as ``null``; nothing is defaulted to zero so an absent reading cannot
read as a measurement.
"""

from __future__ import annotations

import os
import platform
import re
import sys
from pathlib import Path

from animalite.contracts.enums import EvidenceStatus, MemoryMethod
from animalite.contracts.host import HostApproval, HostInventory, ToolIdentity
from animalite.core.logging import utc_now
from animalite.core.resources import THREAD_ENV_VARS, MemorySampler
from animalite.media.ffmpeg import FFmpegTools

__all__ = ["collect_inventory"]

_SIMD_FLAGS = ("avx", "avx2", "avx512f", "sse4_2", "fma", "neon", "asimd", "sve")


def _cpuinfo() -> dict[str, str]:
    try:
        text = Path("/proc/cpuinfo").read_text()
    except OSError:
        return {}
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields.setdefault(key.strip().lower(), value.strip())
    return fields


def _physical_cores(info: dict[str, str]) -> int | None:
    """Physical cores from /proc/cpuinfo core ids, not a guess from logical count."""
    try:
        text = Path("/proc/cpuinfo").read_text()
    except OSError:
        return None
    pairs = set()
    physical_id = core_id = None
    for line in text.splitlines():
        if line.startswith("physical id"):
            physical_id = line.split(":", 1)[1].strip()
        elif line.startswith("core id"):
            core_id = line.split(":", 1)[1].strip()
            if physical_id is not None:
                pairs.add((physical_id, core_id))
    if pairs:
        return len(pairs)
    cpu_cores = info.get("cpu cores")
    return int(cpu_cores) if cpu_cores and cpu_cores.isdigit() else None


def _meminfo_bytes(key: str) -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith(f"{key}:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def _cgroup_memory_max() -> int | None:
    for candidate in (
        Path("/sys/fs/cgroup/memory.max"),
        Path("/sys/fs/cgroup/memory/memory.limit_in_bytes"),
    ):
        try:
            raw = candidate.read_text().strip()
        except OSError:
            continue
        if raw == "max":
            return None
        try:
            value = int(raw)
        except ValueError:
            continue
        # cgroup v1 reports an effectively unlimited sentinel near 2**63.
        return None if value >= 2**62 else value
    return None


def _virtualization_hints() -> list[str]:
    hints: list[str] = []
    for path, label in (
        (Path("/sys/hypervisor/type"), "sys.hypervisor"),
        (Path("/sys/class/dmi/id/product_name"), "dmi.product_name"),
        (Path("/sys/class/dmi/id/sys_vendor"), "dmi.sys_vendor"),
    ):
        try:
            value = path.read_text().strip()
        except OSError:
            continue
        if value:
            hints.append(f"{label}={value}")
    if Path("/.dockerenv").exists():
        hints.append("container=/.dockerenv present")
    if _cgroup_memory_max() is not None:
        hints.append("cgroup memory limit is set; this host is resource-constrained")
    return hints


def _accelerator_notes() -> list[str]:
    """Record what *was* looked at, without claiming a proof of absence."""
    notes = [
        "This is a presence scan of well-known device nodes only. It is not proof "
        "that no accelerator was used; MR-015 and AT-056 require runtime/device "
        "traces from an actual inference run.",
    ]
    for path, label in (
        (Path("/dev/nvidia0"), "NVIDIA device node"),
        (Path("/dev/kfd"), "AMD ROCm device node"),
        (Path("/dev/dri"), "DRM render node directory"),
        (Path("/dev/accel"), "generic accelerator node"),
    ):
        notes.append(f"{label} ({path}): {'present' if path.exists() else 'absent'}")
    return notes


def collect_inventory(*, tools: FFmpegTools | None = None) -> HostInventory:
    """Collect host facts, tool identities and the available measurement method."""
    info = _cpuinfo()
    resolved = tools if tools is not None else FFmpegTools.discover()
    tool_list: list[ToolIdentity] = [resolved.ffmpeg, resolved.ffprobe]

    flags_line = info.get("flags") or info.get("features") or ""
    present_flags = sorted(set(flags_line.split()) & set(_SIMD_FLAGS))

    method = MemorySampler.available_method()
    if method is MemoryMethod.CGROUP_V2_MEMORY_PEAK:
        scope = "application_group_cgroup"
        status = EvidenceStatus.MEASURED
    elif method is MemoryMethod.PROC_VMHWM_PLUS_CHILD_MAXRSS:
        scope = "parent_plus_reaped_children"
        status = EvidenceStatus.MEASURED
    else:
        scope = "unknown"
        status = EvidenceStatus.UNAVAILABLE

    warnings: list[str] = []
    if method is not MemoryMethod.CGROUP_V2_MEMORY_PEAK:
        warnings.append(
            "No cgroup peak counter is available, so a true simultaneous "
            "application-group peak cannot be measured here. The section 12.0 "
            "<=4 GiB memory condition cannot be evidenced on this host."
        )
    if not resolved.available:
        warnings.append(f"FFmpeg tooling unavailable: {resolved.unavailable_reason}")
    for tool in tool_list:
        if tool.available and "--enable-gpl" in (tool.license_relevant_flags or []):
            warnings.append(
                f"{tool.name} is a GPL-configured build; its terms flow from the "
                "enabled components. See THIRD_PARTY_NOTICES.md and docs/licensing.md."
            )

    return HostInventory(
        collected_at=utc_now(),
        hostname_recorded=False,
        os_name=platform.system(),
        os_release=platform.release(),
        os_version=platform.version(),
        kernel=platform.uname().release,
        architecture=platform.machine(),
        libc="-".join(x for x in platform.libc_ver() if x) or None,
        cpu_model=info.get("model name") or info.get("hardware") or platform.processor() or None,
        physical_cores=_physical_cores(info),
        logical_cores=os.cpu_count(),
        cpu_flags_recorded=present_flags,
        cpu_max_mhz=_cpu_max_mhz(),
        total_ram_bytes=_meminfo_bytes("MemTotal"),
        cgroup_memory_max_bytes=_cgroup_memory_max(),
        swap_total_bytes=_meminfo_bytes("SwapTotal"),
        python_version=sys.version.split()[0],
        python_implementation=platform.python_implementation(),
        python_executable=sys.executable,
        thread_environment={
            name: os.environ[name] for name in THREAD_ENV_VARS if name in os.environ
        },
        tools=tool_list,
        memory_measurement_method=method,
        memory_measurement_status=status,
        memory_measurement_scope=scope,
        accelerator_probe_status=EvidenceStatus.PENDING,
        accelerator_probe_notes=_accelerator_notes(),
        approval=HostApproval(),
        virtualization_hints=_virtualization_hints(),
        warnings=warnings,
    )


def _cpu_max_mhz() -> float | None:
    try:
        raw = Path("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq").read_text()
        return int(raw.strip()) / 1000.0
    except (OSError, ValueError):
        pass
    info = _cpuinfo()
    match = re.search(r"([\d.]+)", info.get("cpu mhz", ""))
    return float(match.group(1)) if match else None
