"""Discovery and verification of the pinned RIFE/ncnn CPU runtime.

Handoff rule 7: "Verify the approved binary and weight hashes before use."
Nothing here downloads anything implicitly, and nothing is bundled in the
repository: the operator installs the pinned release out of band (see
``animalite runtime``), and this module resolves it, verifies every declared
artifact against its recorded SHA-256, and refuses to report a runtime as
usable when a hash does not match.

Layout expected under the runtime root::

    <root>/rife-ncnn-vulkan-20221029/
        rife-ncnn-vulkan          # executable
        rife-v4.6/flownet.param
        rife-v4.6/flownet.bin

Overridable with ``ANIMALITE_RIFE_BIN`` and ``ANIMALITE_RIFE_MODELS``.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from animalite.contracts.base import sha256_file

__all__ = [
    "PINNED_MODELS",
    "RIFE_RELEASE",
    "RifeModel",
    "RifeRuntime",
    "RuntimeVerification",
    "default_runtime_root",
]

#: The pinned upstream release. Recorded so a report can name exactly what ran.
RIFE_RELEASE = {
    "name": "rife-ncnn-vulkan",
    "version": "20221029-ubuntu",
    "source_url": (
        "https://github.com/nihui/rife-ncnn-vulkan/releases/download/"
        "20221029/rife-ncnn-vulkan-20221029-ubuntu.zip"
    ),
    "archive_sha256": "1e2c7ee7fa7daa326542d50622f0afedc80cf6f1858bda411d16385ffa5cdf68",
    "archive_bytes": "431302796",
    "binary_sha256": "5c256556195216ddfca103073b0fd37e33e154c8aa40666775fcae8d6a6580b4",
    "code_license": "MIT",
    "runtime_license": "BSD-3-Clause (ncnn, Tencent)",
}

DIRECTORY_NAME = "rife-ncnn-vulkan-20221029"
BINARY_NAME = "rife-ncnn-vulkan"


@dataclass(frozen=True)
class RifeModel:
    """One pinned RIFE checkpoint and, crucially, what it actually supports.

    ``supports_arbitrary_timestep`` is not cosmetic. The v4 architecture takes a
    timestep and interpolates at it. The earlier contextnet/fusionnet models are
    2x midpoint models: given ``-s 0.25`` they do **not** fail, they return a
    plausible-looking frame that is temporally wrong. Measured on
    ``rife-anime`` (see DEC-0012), the subject moved *backwards* between
    t=0.25 and t=0.50. Using such a model off-midpoint is therefore rejected
    rather than trusted.
    """

    name: str
    supports_arbitrary_timestep: bool
    file_hashes: dict[str, str]
    architecture: str
    notes: str = ""

    @property
    def files(self) -> tuple[str, ...]:
        return tuple(sorted(self.file_hashes))


PINNED_MODELS: dict[str, RifeModel] = {
    "rife-v4.6": RifeModel(
        name="rife-v4.6",
        supports_arbitrary_timestep=True,
        architecture="v4 (flownet only)",
        file_hashes={
            "flownet.param": ("724569596bcd1e7b9fa50455c604777ebed99746d2ef40aa86e31b5725f1053c"),
            "flownet.bin": ("f334ed2260149ce0188a6dcf049844e8b0cdd912e01cbcfb63553157d2508958"),
        },
        notes="Honours -s across 0..1; verified monotonic on a synthetic ramp.",
    ),
    "rife-anime": RifeModel(
        name="rife-anime",
        supports_arbitrary_timestep=False,
        architecture="v2-era (flownet + contextnet + fusionnet)",
        file_hashes={},  # not pinned: excluded from use, see notes
        notes=(
            "MIDPOINT ONLY. Measured non-monotonic output when given an "
            "arbitrary timestep, so it is declared here to be rejected rather "
            "than silently misused. Not pinned or verified."
        ),
    ),
}


def default_runtime_root() -> Path:
    """Where an installed runtime is looked for by default."""
    override = os.environ.get("ANIMALITE_RUNTIME_DIR")
    if override:
        return Path(override)
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "animalite" / "runtimes"


@dataclass
class RuntimeVerification:
    """Result of checking an installed runtime against the pinned hashes."""

    binary_present: bool = False
    binary_verified: bool = False
    model_present: bool = False
    model_verified: bool = False
    problems: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return self.binary_verified and self.model_verified and not self.problems


@dataclass(frozen=True)
class RifeRuntime:
    """A resolved (not necessarily verified) RIFE/ncnn installation."""

    binary_path: Path | None
    models_root: Path | None
    root: Path

    @classmethod
    def discover(cls, root: Path | None = None) -> RifeRuntime:
        base = root if root is not None else default_runtime_root()
        install = base / DIRECTORY_NAME

        binary_override = os.environ.get("ANIMALITE_RIFE_BIN")
        models_override = os.environ.get("ANIMALITE_RIFE_MODELS")

        binary = Path(binary_override) if binary_override else install / BINARY_NAME
        models = Path(models_override) if models_override else install
        return cls(
            binary_path=binary if binary.is_file() else None,
            models_root=models if models.is_dir() else None,
            root=base,
        )

    @property
    def available(self) -> bool:
        return self.binary_path is not None and self.models_root is not None

    def model_dir(self, model_name: str) -> Path | None:
        if self.models_root is None:
            return None
        candidate = self.models_root / model_name
        return candidate if candidate.is_dir() else None

    def verify(self, model_name: str) -> RuntimeVerification:
        """Verify the binary and one model against their pinned digests."""
        result = RuntimeVerification()

        model = PINNED_MODELS.get(model_name)
        if model is None:
            result.problems.append(
                f"model {model_name!r} is not pinned; known: {sorted(PINNED_MODELS)}"
            )
            return result
        if not model.file_hashes:
            result.problems.append(
                f"model {model_name!r} has no pinned digests and must not be used: {model.notes}"
            )
            return result

        if self.binary_path is None:
            result.problems.append(
                "rife-ncnn-vulkan executable not found. Install the pinned release "
                "or set ANIMALITE_RIFE_BIN."
            )
        else:
            result.binary_present = True
            actual = sha256_file(str(self.binary_path)).removeprefix("sha256:")
            expected = RIFE_RELEASE["binary_sha256"]
            if actual == expected:
                result.binary_verified = True
            else:
                result.problems.append(
                    f"binary digest mismatch for {self.binary_path}: expected "
                    f"{expected}, found {actual}"
                )

        directory = self.model_dir(model_name)
        if directory is None:
            result.problems.append(
                f"model directory {model_name!r} not found under {self.models_root}"
            )
            return result

        result.model_present = True
        mismatches: list[str] = []
        for filename, expected_digest in sorted(model.file_hashes.items()):
            path = directory / filename
            if not path.is_file():
                mismatches.append(f"missing {filename}")
                continue
            actual_digest = sha256_file(str(path)).removeprefix("sha256:")
            if actual_digest != expected_digest:
                mismatches.append(f"{filename}: expected {expected_digest}, found {actual_digest}")
        if mismatches:
            result.problems.extend(f"weight verification failed: {m}" for m in mismatches)
        else:
            result.model_verified = True
        return result

    def version_probe(self, timeout: float = 30.0) -> str | None:
        """Run the executable with no arguments to capture its usage banner.

        The tool has no ``--version``; the usage text is the only identity it
        prints. The pinned digest is the real identity check.
        """
        if self.binary_path is None:
            return None
        try:
            completed = subprocess.run(  # noqa: S603 - argv list, no shell
                [str(self.binary_path)],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return f"probe failed: {type(exc).__name__}: {exc}"
        lines = (completed.stdout + completed.stderr).splitlines()
        usage = next((ln.strip() for ln in lines if ln.startswith("Usage:")), None)
        return usage or (lines[0].strip() if lines else None)
