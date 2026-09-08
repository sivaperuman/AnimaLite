"""Thread budgeting and process-group peak-memory sampling.

Leaf module (see :mod:`animalite.proc` for why): it imports only from
:mod:`animalite.contracts`.

Handoff rule 6: "Record the combined app/worker/encoder memory method;
measuring only the Python parent is insufficient."

Three methods are tried in order of fidelity:

1. **cgroup v2 ``memory.peak``** -- a true high-water mark for the whole cgroup,
   covering the Python process, any native worker and the encoder.
2. **``/proc/self/status:VmHWM`` + ``getrusage(RUSAGE_CHILDREN).ru_maxrss``** --
   the parent's peak plus the largest peak of any *reaped* child. This is an
   upper bound on neither simultaneity nor concurrency, so the caveat is
   recorded with the observation rather than hidden.
3. **Nothing measurable** -- the observation is ``unavailable``. It is never
   reported as zero.
"""

from __future__ import annotations

import contextlib
import os
import resource
import sys
from dataclasses import dataclass
from pathlib import Path

from animalite.contracts.enums import EvidenceStatus, MemoryMethod
from animalite.contracts.profile import ThreadBudget
from animalite.contracts.results import MemoryObservation

__all__ = ["MemorySampler", "thread_environment"]

_CGROUP_PEAK_CANDIDATES = (
    Path("/sys/fs/cgroup/memory.peak"),
    Path("/sys/fs/cgroup/memory/memory.max_usage_in_bytes"),
)

#: Environment variables that pin native library thread pools. Set for every
#: child process so a native runtime cannot silently oversubscribe the host.
THREAD_ENV_VARS = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
)


def thread_environment(budget: ThreadBudget) -> dict[str, str]:
    """Environment overrides pinning native thread pools to the budget."""
    env = {name: str(budget.inference_threads or 1) for name in THREAD_ENV_VARS}
    env["ANIMALITE_TOTAL_THREADS"] = str(budget.total_threads)
    env["ANIMALITE_ENCODER_THREADS"] = str(budget.encoder_threads)
    return env


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def _proc_vmhwm_bytes() -> int | None:
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmHWM:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def _child_maxrss_bytes() -> int | None:
    try:
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    except (OSError, ValueError):  # pragma: no cover - platform dependent
        return None
    # ru_maxrss is kilobytes on Linux and bytes on macOS.
    factor = 1 if sys.platform == "darwin" else 1024
    return int(usage.ru_maxrss) * factor


@dataclass
class MemorySampler:
    """Samples a peak-memory high-water mark across a measured region.

    ``start()`` records the baseline; ``observe()`` returns the peak reached
    since then, with the method and scope that produced it.
    """

    cgroup_path: Path | None = None
    _baseline_cgroup: int | None = None
    _baseline_child: int | None = None

    @staticmethod
    def detect_cgroup_peak_file() -> Path | None:
        for candidate in _CGROUP_PEAK_CANDIDATES:
            if candidate.exists() and _read_int(candidate) is not None:
                return candidate
        return None

    @staticmethod
    def available_method() -> MemoryMethod:
        if MemorySampler.detect_cgroup_peak_file() is not None:
            return MemoryMethod.CGROUP_V2_MEMORY_PEAK
        if _proc_vmhwm_bytes() is not None:
            return MemoryMethod.PROC_VMHWM_PLUS_CHILD_MAXRSS
        return MemoryMethod.NONE

    def start(self) -> None:
        self.cgroup_path = self.detect_cgroup_peak_file()
        if self.cgroup_path is not None:
            # memory.peak is resettable on newer kernels; when it is not, the
            # baseline is subtracted instead so the delta stays attributable.
            with contextlib.suppress(OSError):
                self.cgroup_path.write_text("reset\n")
            self._baseline_cgroup = _read_int(self.cgroup_path)
        self._baseline_child = _child_maxrss_bytes()

    def observe(self) -> MemoryObservation:
        if self.cgroup_path is not None:
            peak = _read_int(self.cgroup_path)
            if peak is not None:
                caveats = [
                    f"cgroup peak read from {self.cgroup_path}",
                    "covers every process in this cgroup, including unrelated ones",
                ]
                if self._baseline_cgroup is not None and peak >= self._baseline_cgroup:
                    caveats.append(
                        f"baseline at start was {self._baseline_cgroup} bytes and is "
                        "not subtracted; the value is an absolute cgroup high-water mark"
                    )
                return MemoryObservation(
                    status=EvidenceStatus.MEASURED,
                    method=MemoryMethod.CGROUP_V2_MEMORY_PEAK,
                    peak_bytes=peak,
                    scope="application_group_cgroup",
                    caveats=caveats,
                )

        parent = _proc_vmhwm_bytes()
        if parent is None:
            return MemoryObservation.unavailable(
                "no cgroup memory.peak and no /proc/self/status VmHWM on this platform"
            )
        child = _child_maxrss_bytes() or 0
        return MemoryObservation(
            status=EvidenceStatus.MEASURED,
            method=MemoryMethod.PROC_VMHWM_PLUS_CHILD_MAXRSS,
            peak_bytes=parent + child,
            scope="parent_plus_reaped_children",
            caveats=[
                "sum of the parent high-water mark and the largest reaped child peak",
                "peaks may not have occurred simultaneously; this is not a true "
                "process-group simultaneous peak",
                "not sufficient evidence for the section 12.0 <=4 GiB application "
                "memory condition; that requires a cgroup or equivalent group measure",
            ],
        )


def apply_thread_environment(
    budget: ThreadBudget, env: dict[str, str] | None = None
) -> dict[str, str]:
    """Return a child environment with the thread budget applied."""
    base = dict(os.environ if env is None else env)
    base.update(thread_environment(budget))
    return base
