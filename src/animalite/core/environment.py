"""Reproducibility inputs captured for every attempt (handoff rule 8)."""

from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path

from animalite import SCHEMA_VERSION, __version__
from animalite.contracts.base import sha256_file
from animalite.contracts.job import EnvironmentRecord
from animalite.contracts.profile import ThreadBudget
from animalite.core.resources import thread_environment
from animalite.media.ffmpeg import FFmpegTools

__all__ = ["capture_environment", "git_state", "repo_root"]


def repo_root(start: Path | None = None) -> Path | None:
    """Nearest ancestor containing a ``.git`` entry, or ``None``."""
    here = (start or Path(__file__)).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def git_state(root: Path | None = None) -> tuple[str | None, bool | None]:
    """Return ``(commit, dirty)``; ``(None, None)`` outside a git checkout.

    Dirty-tree status matters: a timing recorded against a commit that does not
    describe the tree that ran is not reproducible evidence.
    """
    base = root or repo_root()
    if base is None:
        return None, None
    try:
        commit = subprocess.run(  # noqa: S603 - argv list, no shell
            ["git", "-C", str(base), "rev-parse", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        status = subprocess.run(  # noqa: S603
            ["git", "-C", str(base), "status", "--porcelain"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None, None
    if commit.returncode != 0:
        return None, None
    return commit.stdout.strip(), bool(status.stdout.strip())


def _lock_digest() -> str | None:
    base = repo_root()
    if base is None:
        return None
    lock = base / "constraints" / "dev-linux-cpython311.txt"
    return sha256_file(str(lock)) if lock.is_file() else None


def _cpu_flags() -> list[str]:
    """SIMD-relevant CPU flags, recorded because they change numeric output."""
    interesting = ("avx2", "avx512f", "sse4_2", "fma", "neon", "asimd")
    try:
        text = Path("/proc/cpuinfo").read_text()
    except OSError:
        return []
    for line in text.splitlines():
        if line.startswith("flags") or line.startswith("Features"):
            present = set(line.split(":", 1)[1].split())
            return sorted(f for f in interesting if f in present)
    return []


def capture_environment(
    thread_budget: ThreadBudget, tools: FFmpegTools | None = None
) -> EnvironmentRecord:
    commit, dirty = git_state()
    resolved = tools if tools is not None else FFmpegTools.discover()
    return EnvironmentRecord(
        animalite_version=__version__,
        schema_version=SCHEMA_VERSION,
        code_commit=commit,
        code_tree_dirty=dirty,
        python_version=sys.version.split()[0],
        platform=platform.platform(),
        architecture=platform.machine(),
        thread_environment=thread_environment(thread_budget),
        tool_identities=resolved.identity_map(),
        dependency_lock_digest=_lock_digest(),
        cpu_flags_recorded=_cpu_flags(),
    )
