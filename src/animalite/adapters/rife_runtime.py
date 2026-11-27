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
import platform
import struct
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from animalite.contracts.base import sha256_file
from animalite.errors import AdapterError
from animalite.proc import ProcessFailure, run_capture

__all__ = [
    "PINNED_MODELS",
    "RIFE_RELEASE",
    "BinaryInspection",
    "RifeModel",
    "RifeRuntime",
    "RuntimeInspection",
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
    timestep and interpolates at it; the earlier contextnet/fusionnet models are
    2x midpoint models and cannot serve an arbitrary one.

    The pinned wrapper refuses the combination outright -- a non-v4 model with a
    non-0.5 timestep prints "only rife-v4 model support custom numframe and
    timestep" and exits -1. So the failure is a mid-render subprocess error, and
    rejecting at validation turns it into an actionable message before anything
    runs. (An earlier version of this note claimed such a model silently returns
    a temporally wrong frame; that explanation is withdrawn as unverified, see
    DEC-0011.)
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
            "MIDPOINT ONLY. Declared here so that selecting it produces an "
            "explicit rejection at validation rather than a subprocess error "
            "mid-render: the pinned binary exits -1 for a non-0.5 timestep. "
            "Not pinned or verified."
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


#: ELF ``e_machine`` values for the architectures this project can run on, keyed
#: by what ``platform.machine()`` reports. Read from the file's header; nothing
#: is executed to obtain it.
_ELF_MACHINES = {
    "x86_64": 0x3E,
    "amd64": 0x3E,
    "aarch64": 0xB7,
    "arm64": 0xB7,
}

#: Directories searched for a required shared library. Not a substitute for the
#: dynamic loader -- it does not read /etc/ld.so.conf or the cache -- so a
#: negative result is reported as "not found in the usual places", not as proof.
_LIBRARY_PATHS = (
    "/lib",
    "/usr/lib",
    "/usr/local/lib",
    "/lib64",
    "/usr/lib64",
    "/lib/x86_64-linux-gnu",
    "/usr/lib/x86_64-linux-gnu",
    "/lib/aarch64-linux-gnu",
    "/usr/lib/aarch64-linux-gnu",
)


@dataclass(frozen=True)
class BinaryInspection:
    """What the executable's *bytes* say, read without running them."""

    is_elf: bool = False
    elf_class: int = 0
    machine: int = 0
    executable_bit: bool = False
    needed_libraries: tuple[str, ...] = ()
    missing_libraries: tuple[str, ...] = ()
    problems: tuple[str, ...] = ()

    @property
    def compatible(self) -> bool:
        return (
            self.is_elf and self.executable_bit and not self.missing_libraries and not self.problems
        )


def _inspect_binary(path: Path) -> BinaryInspection:
    """Read the ELF header and dynamic section. Never executes the file.

    ``ldd`` is not used and cannot be: it works by invoking the dynamic loader
    on the target, which runs code from the very file whose trustworthiness is
    in question. The header is parsed here instead, which is enough to answer
    the questions that matter -- is this an executable for this machine, and are
    the libraries it names present.
    """
    problems: list[str] = []
    try:
        mode = path.stat().st_mode
        executable = bool(mode & 0o111)
        data = path.read_bytes()
    except OSError as exc:
        return BinaryInspection(problems=(f"cannot read {path}: {exc}",))

    if len(data) < 64 or data[:4] != b"\x7fELF":
        return BinaryInspection(
            executable_bit=executable,
            problems=(
                f"{path} is not an ELF executable (first bytes {data[:4]!r}); "
                "the pinned release is a Linux binary",
            ),
        )

    elf_class = data[4]  # 1 = 32-bit, 2 = 64-bit
    little = data[5] == 1
    endian = "<" if little else ">"
    if elf_class != 2:
        problems.append(
            f"{path} declares ELF class {elf_class} (1 = 32-bit); the pinned "
            "release is a 64-bit binary"
        )
    machine = struct.unpack_from(f"{endian}H", data, 18)[0]
    expected = _ELF_MACHINES.get(platform.machine().lower())
    if sys.platform != "linux":
        problems.append(
            f"the pinned release is a Linux ELF binary and this host is {sys.platform!r}"
        )
    elif expected is None:
        problems.append(
            f"unknown host architecture {platform.machine()!r}; cannot confirm the "
            "executable matches this machine"
        )
    elif machine != expected:
        problems.append(
            f"{path} is built for ELF machine {machine:#x}; this host is "
            f"{platform.machine()} ({expected:#x})"
        )
    if not executable:
        problems.append(f"{path} is not marked executable (mode {mode & 0o777:#o})")

    needed = _needed_libraries(data, endian)
    missing = tuple(
        name
        for name in needed
        if not any((Path(directory) / name).exists() for directory in _LIBRARY_PATHS)
    )
    return BinaryInspection(
        is_elf=True,
        elf_class=elf_class,
        machine=machine,
        executable_bit=executable,
        needed_libraries=needed,
        missing_libraries=missing,
        problems=tuple(problems),
    )


def _needed_libraries(data: bytes, endian: str) -> tuple[str, ...]:
    """Shared libraries named in the ELF dynamic section (best effort).

    Walks the program headers to PT_DYNAMIC, resolves DT_STRTAB through the
    PT_LOAD mappings and reads the DT_NEEDED names. Returns nothing at all when
    the structure is not what is expected: a partial parse must not be reported
    as "this binary needs no libraries".
    """
    try:
        phoff = struct.unpack_from(f"{endian}Q", data, 32)[0]
        phentsize = struct.unpack_from(f"{endian}H", data, 54)[0]
        phnum = struct.unpack_from(f"{endian}H", data, 56)[0]
        loads: list[tuple[int, int, int]] = []  # (vaddr, offset, filesz)
        dynamic: tuple[int, int] | None = None
        for index in range(phnum):
            base = phoff + index * phentsize
            p_type = struct.unpack_from(f"{endian}I", data, base)[0]
            p_offset = struct.unpack_from(f"{endian}Q", data, base + 8)[0]
            p_vaddr = struct.unpack_from(f"{endian}Q", data, base + 16)[0]
            p_filesz = struct.unpack_from(f"{endian}Q", data, base + 32)[0]
            if p_type == 1:  # PT_LOAD
                loads.append((p_vaddr, p_offset, p_filesz))
            elif p_type == 2:  # PT_DYNAMIC
                dynamic = (p_offset, p_filesz)
        if dynamic is None:
            return ()

        def to_offset(vaddr: int) -> int | None:
            for start, offset, size in loads:
                if start <= vaddr < start + size:
                    return offset + (vaddr - start)
            return None

        needed_offsets: list[int] = []
        strtab = None
        cursor, size = dynamic
        for position in range(cursor, cursor + size, 16):
            tag, value = struct.unpack_from(f"{endian}QQ", data, position)
            if tag == 0:  # DT_NULL
                break
            if tag == 1:  # DT_NEEDED
                needed_offsets.append(value)
            elif tag == 5:  # DT_STRTAB
                strtab = to_offset(value)
        if strtab is None:
            return ()
        names: list[str] = []
        for offset in needed_offsets:
            end = data.index(b"\x00", strtab + offset)
            names.append(data[strtab + offset : end].decode("utf-8", "replace"))
        return tuple(names)
    except (struct.error, ValueError, IndexError):  # pragma: no cover - malformed ELF
        return ()


@dataclass(frozen=True)
class RuntimeInspection:
    """The four questions ``runtime status`` has to keep apart.

    Conflating them is what let a status report say ``binary_verified=false``
    and still execute the file to print a banner. Installed is about presence,
    verified is about bytes, compatible is about this machine, and admitted is
    about permission -- and a "usable" claim requires all four.
    """

    model: str
    verification: RuntimeVerification
    binary: BinaryInspection

    @property
    def installed(self) -> bool:
        return self.verification.binary_present and self.verification.model_present

    @property
    def verified(self) -> bool:
        return self.verification.binary_verified and self.verification.model_verified

    @property
    def compatible(self) -> bool:
        """Only meaningful once verified: unverified bytes describe nothing."""
        return self.verified and self.binary.compatible

    @property
    def problems(self) -> list[str]:
        return [*self.verification.problems, *self.binary.problems, *self._library_problems()]

    def _library_problems(self) -> list[str]:
        if not self.binary.missing_libraries:
            return []
        return [
            "shared librar(y/ies) named by the executable were not found in the "
            f"usual search paths: {', '.join(self.binary.missing_libraries)}. "
            "Install them (the pinned build links libvulkan even for CPU use) or "
            "set LD_LIBRARY_PATH."
        ]


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

    def inspect(self, model_name: str) -> RuntimeInspection:
        """Verify digests and read the executable's headers. Executes nothing.

        This is what ``runtime status`` calls. The previous status path ran the
        binary to capture its usage banner whenever a file existed -- including
        after its digest had failed -- so a tampered executable was executed by
        the very command reporting that it could not be trusted.
        """
        verification = self.verify(model_name)
        binary = (
            _inspect_binary(self.binary_path)
            if self.binary_path is not None
            else BinaryInspection(problems=("no executable resolved",))
        )
        return RuntimeInspection(model=model_name, verification=verification, binary=binary)

    def version_probe(
        self,
        inspection: RuntimeInspection,
        *,
        timeout: float = 30.0,
        cancel: Callable[[], bool] | None = None,
    ) -> str | None:
        """Run the executable with no arguments to capture its usage banner.

        The tool has no ``--version``; the usage text is the only identity it
        prints, and the pinned digest is the real identity check anyway -- which
        is why this refuses to run anything that has not already matched it.
        Passing the inspection rather than a boolean makes that impossible to
        skip by forgetting an argument.

        Supervised like every other native call: process-group ownership,
        bounded capture, one absolute deadline.
        """
        if not inspection.verified:
            raise AdapterError(
                "refusing to execute the runtime: its pinned digests have not been "
                f"verified ({'; '.join(inspection.problems) or 'unverified'})"
            )
        if self.binary_path is None:  # pragma: no cover - verified implies present
            return None
        try:
            completed = run_capture([str(self.binary_path)], timeout=timeout, cancel=cancel)
        except ProcessFailure as exc:
            return f"probe failed: {type(exc).__name__}: {exc}"
        except OSError as exc:
            return f"probe failed: {type(exc).__name__}: {exc}"
        text = (completed.stdout + completed.stderr).decode("utf-8", "replace")
        lines = text.splitlines()
        usage = next((ln.strip() for ln in lines if ln.startswith("Usage:")), None)
        return usage or (lines[0].strip() if lines else None)
