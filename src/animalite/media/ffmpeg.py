"""FFmpeg/FFprobe discovery and invocation.

Handoff rule 7: "Invoke native tools with argument arrays rather than
shell-expanded user paths." Every call here builds an ``argv`` list and runs it
without a shell. Handoff section 0: FFmpeg is an explicitly installed external
executable; nothing is bundled.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from animalite.contracts.host import ToolIdentity
from animalite.errors import ToolUnavailableError

__all__ = ["LICENSE_RELEVANT_FLAGS", "FFmpegTools", "probe_tool"]

#: Build flags that change FFmpeg's own licensing outcome. Recorded verbatim so
#: a GPL or nonfree build is visible rather than assumed. See
#: https://ffmpeg.org/legal.html
LICENSE_RELEVANT_FLAGS = (
    "--enable-gpl",
    "--enable-nonfree",
    "--enable-version3",
    "--enable-libx264",
    "--enable-libx265",
    "--enable-libfdk-aac",
)

_VERSION_RE = re.compile(r"^(?:ffmpeg|ffprobe) version (\S+)")
_CONFIG_RE = re.compile(r"^\s*configuration:\s*(.*)$", re.MULTILINE)


def _resolve(name: str, env_var: str) -> str | None:
    override = os.environ.get(env_var)
    if override:
        return override if Path(override).exists() else None
    return shutil.which(name)


def probe_tool(name: str, env_var: str, *, timeout: float = 20.0) -> ToolIdentity:
    """Record the identity of an installed FFmpeg-family executable.

    Never raises: an absent or unrunnable tool is reported as
    ``available=False`` with the error text, which is what ``doctor`` and the
    pending-test policy consume.
    """
    path = _resolve(name, env_var)
    if path is None:
        return ToolIdentity(
            name=name,
            available=False,
            error=f"{name} not found on PATH and {env_var} is unset or points at a missing file",
        )
    try:
        completed = subprocess.run(  # noqa: S603 - argv list, no shell
            [path, "-hide_banner", "-version"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return ToolIdentity(
            name=name, available=False, path=path, error=f"{type(exc).__name__}: {exc}"
        )

    if completed.returncode != 0:
        return ToolIdentity(
            name=name,
            available=False,
            path=path,
            error=f"exit {completed.returncode}: {completed.stderr.strip()[:400]}",
        )

    stdout = completed.stdout
    version_match = _VERSION_RE.search(stdout)
    config_match = _CONFIG_RE.search(stdout)
    configuration = config_match.group(1).strip() if config_match else None
    flags = [f for f in LICENSE_RELEVANT_FLAGS if configuration and f in configuration]
    return ToolIdentity(
        name=name,
        available=True,
        path=path,
        version=version_match.group(1) if version_match else None,
        build_configuration=configuration,
        license_relevant_flags=flags,
    )


@dataclass(frozen=True)
class FFmpegTools:
    """A resolved ffmpeg/ffprobe pair."""

    ffmpeg: ToolIdentity
    ffprobe: ToolIdentity

    @classmethod
    def discover(cls) -> FFmpegTools:
        return cls(
            ffmpeg=probe_tool("ffmpeg", "ANIMALITE_FFMPEG"),
            ffprobe=probe_tool("ffprobe", "ANIMALITE_FFPROBE"),
        )

    @property
    def available(self) -> bool:
        return self.ffmpeg.available and self.ffprobe.available

    @property
    def unavailable_reason(self) -> str | None:
        missing = [t.error for t in (self.ffmpeg, self.ffprobe) if not t.available]
        return "; ".join(e for e in missing if e) or None

    def require(self) -> FFmpegTools:
        if not self.available:
            raise ToolUnavailableError(
                f"FFmpeg tooling is unavailable: {self.unavailable_reason}. "
                "Install FFmpeg (providing ffmpeg and ffprobe) or set ANIMALITE_FFMPEG "
                "and ANIMALITE_FFPROBE."
            )
        return self

    @property
    def ffmpeg_path(self) -> str:
        path = self.require().ffmpeg.path
        assert path is not None  # guaranteed by available=True
        return path

    @property
    def ffprobe_path(self) -> str:
        path = self.require().ffprobe.path
        assert path is not None
        return path

    def identity_map(self) -> dict[str, str]:
        """Compact identity strings for the attempt environment record."""
        out: dict[str, str] = {}
        for tool in (self.ffmpeg, self.ffprobe):
            if tool.available and tool.version:
                out[tool.name] = tool.version
                if tool.license_relevant_flags:
                    out[f"{tool.name}_license_flags"] = ",".join(tool.license_relevant_flags)
        return out
