"""Bounded, explicit provisioning of the pinned RIFE/ncnn runtime (B-2).

Nothing here runs implicitly. There is no automatic fetch during render, during
validation or during tests: the operator asks for it, and this module is what
"asking" runs. What it does *not* do is as important as what it does -- it never
executes a downloaded byte, and it verifies before it extracts.

The failure modes it is built against, in order of how badly they end:

* **A tampered or truncated archive.** The digest is checked against the pinned
  value before a single member is extracted, so a corrupted download cannot put
  files on disk at all.
* **Path traversal and symlinks in the archive.** A zip entry may name
  ``../../.ssh/authorized_keys`` or be a symlink pointing anywhere; both are
  rejected by inspecting the member list, before extraction.
* **Decompression bombs.** Members declare their uncompressed size, and the
  running total is capped -- checked against the declared size before extracting
  and against the real byte count while writing, because a declared size is
  attacker-controlled.
* **An interrupted install replacing a good one.** Everything is staged in a
  sibling directory and verified there; the existing install is only moved aside
  once the new one has passed, and is restored if the swap fails.
* **An unbounded transfer.** Both the byte count and the wall clock are capped,
  so a slow-loris server cannot hold the command open indefinitely.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import time
import urllib.request
import zipfile
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

from animalite.adapters.rife_runtime import (
    BINARY_NAME,
    DIRECTORY_NAME,
    PINNED_MODELS,
    RIFE_RELEASE,
    RifeRuntime,
    default_runtime_root,
)
from animalite.contracts.base import sha256_file
from animalite.contracts.enums import FailureCategory
from animalite.errors import AnimaLiteError

__all__ = [
    "DOWNLOAD_TIMEOUT_SECONDS",
    "MAX_ARCHIVE_BYTES",
    "MAX_EXPANDED_BYTES",
    "InstallReport",
    "ProvisioningError",
    "Transport",
    "download_archive",
    "install_archive",
    "provision",
]

#: Hard cap on the download. The pinned archive is 431,302,796 bytes; the margin
#: allows for a re-pinned release without allowing an unbounded transfer.
MAX_ARCHIVE_BYTES = 600_000_000

#: Hard cap on everything written during extraction. Only the executable and one
#: model directory are extracted, which is far smaller than the whole archive.
MAX_EXPANDED_BYTES = 400_000_000

#: Wall-clock cap on the transfer, independent of the byte cap: a stalled or
#: byte-per-second server is bounded by this rather than by patience.
DOWNLOAD_TIMEOUT_SECONDS = 1800.0

#: Per-read socket timeout. Bounds a single stalled read so the wall-clock cap
#: is not the only thing standing between the command and a hung connection.
_SOCKET_TIMEOUT_SECONDS = 60.0

_CHUNK_BYTES = 1024 * 1024

#: Zip external attributes are the st_mode in the high 16 bits. Anything that is
#: not a regular file or a directory -- symlink, device, fifo -- is refused.
_S_IFMT = 0o170000
_S_IFLNK = 0o120000
_S_IFREG = 0o100000
_S_IFDIR = 0o040000


class ProvisioningError(AnimaLiteError):
    """Provisioning refused or failed. Nothing was installed."""

    category = FailureCategory.TOOL_UNAVAILABLE


#: A transport opens a URL and yields a readable binary stream. Injected so the
#: tests exercise truncation, oversize and tampering without a network.
Transport = Callable[[str], AbstractContextManager[IO[bytes]]]


@contextmanager
def default_transport(url: str) -> Iterator[IO[bytes]]:
    """Plain HTTPS GET. The only place this module touches the network."""
    if not url.lower().startswith("https://"):
        raise ProvisioningError(f"refusing to download over a non-HTTPS URL: {url}")
    with urllib.request.urlopen(url, timeout=_SOCKET_TIMEOUT_SECONDS) as response:  # noqa: S310
        yield response


@dataclass(frozen=True)
class InstallReport:
    """What provisioning actually did, for the operator and the log."""

    target: Path
    archive_path: Path | None
    archive_bytes: int
    installed_files: tuple[str, ...]
    binary_verified: bool
    model_verified: bool
    replaced_existing: bool
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def usable(self) -> bool:
        return self.binary_verified and self.model_verified


def download_archive(
    url: str,
    destination: Path,
    *,
    expected_sha256: str,
    max_bytes: int = MAX_ARCHIVE_BYTES,
    timeout_seconds: float = DOWNLOAD_TIMEOUT_SECONDS,
    transport: Transport = default_transport,
) -> Path:
    """Stream ``url`` to ``destination`` under a byte and time cap, then verify.

    The partial file is removed on every failure path. Leaving it behind would
    invite a later run to treat a truncated archive as a cached download, which
    is exactly the confusion the digest check exists to prevent.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_seconds
    digest = hashlib.sha256()
    written = 0
    try:
        with transport(url) as stream, destination.open("wb") as handle:
            while True:
                if time.monotonic() > deadline:
                    raise ProvisioningError(
                        f"download of {url} exceeded {timeout_seconds:.0f}s after "
                        f"{written} bytes; nothing was installed"
                    )
                chunk = stream.read(_CHUNK_BYTES)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise ProvisioningError(
                        f"download of {url} exceeded the {max_bytes} byte cap; "
                        "nothing was installed"
                    )
                digest.update(chunk)
                handle.write(chunk)
    except ProvisioningError:
        destination.unlink(missing_ok=True)
        raise
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise ProvisioningError(f"download of {url} failed: {exc}") from exc

    actual = digest.hexdigest()
    if actual != expected_sha256:
        destination.unlink(missing_ok=True)
        raise ProvisioningError(
            f"archive digest mismatch for {url}: expected sha256:{expected_sha256}, "
            f"downloaded sha256:{actual} ({written} bytes). The file was deleted "
            "and nothing was extracted."
        )
    return destination


def _member_mode(info: zipfile.ZipInfo) -> int:
    """The st_mode a member declares, or 0 when the archive does not say."""
    return (info.external_attr >> 16) & 0xFFFF


def _selected_members(
    archive: zipfile.ZipFile, *, model: str, expected_files: tuple[str, ...]
) -> tuple[list[zipfile.ZipInfo], list[zipfile.ZipInfo]]:
    """The binary and model members to extract, after refusing unsafe ones.

    Only what is needed is extracted. That bounds the expansion, and it keeps
    an archive from installing files nobody asked for simply because they were
    inside it.
    """
    binary: list[zipfile.ZipInfo] = []
    weights: list[zipfile.ZipInfo] = []
    for info in archive.infolist():
        name = info.filename
        mode = _member_mode(info)
        kind = mode & _S_IFMT
        if kind == _S_IFLNK:
            raise ProvisioningError(
                f"archive member {name!r} is a symbolic link; refusing to extract "
                "an archive that can place links outside the install directory"
            )
        # `0` means the archive recorded no mode at all, which is normal for
        # zips written on Windows. Anything else that is neither a regular file
        # nor a directory -- device, fifo, socket -- is refused.
        if kind not in (0, _S_IFREG, _S_IFDIR):
            raise ProvisioningError(
                f"archive member {name!r} is not a regular file or directory "
                f"(mode {mode:#o}); refusing to extract it"
            )
        parts = Path(name).parts
        if name.startswith("/") or ".." in parts or (len(parts) > 1 and parts[0].endswith(":")):
            raise ProvisioningError(
                f"archive member {name!r} escapes the install directory; refusing to extract it"
            )
        if info.is_dir():
            continue
        if parts[-1] == BINARY_NAME:
            binary.append(info)
        elif len(parts) >= 2 and parts[-2] == model:
            weights.append(info)
    if not binary:
        raise ProvisioningError(
            f"archive contains no {BINARY_NAME!r} executable; it is not the pinned release"
        )
    if len(binary) > 1:
        raise ProvisioningError(
            f"archive contains {len(binary)} entries named {BINARY_NAME!r}; refusing "
            "to guess which one to install"
        )
    expected = set(expected_files)
    present = {Path(i.filename).name for i in weights}
    if not expected.issubset(present):
        raise ProvisioningError(
            f"archive does not contain the pinned {model} files "
            f"{sorted(expected - present)}; it is not the pinned release"
        )
    return binary, weights


def _extract_bounded(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    destination: Path,
    *,
    remaining_bytes: int,
) -> int:
    """Extract one member to an exact path, bounded by ``remaining_bytes``.

    The declared ``file_size`` is checked first because it is cheap, and the
    real byte count is checked while writing because the declared size is part
    of the archive and therefore not to be trusted.
    """
    if info.file_size > remaining_bytes:
        raise ProvisioningError(
            f"archive member {info.filename!r} declares {info.file_size} bytes, "
            f"which exceeds the {remaining_bytes} bytes left in the expansion cap"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with archive.open(info) as source, destination.open("wb") as handle:
        while True:
            chunk = source.read(_CHUNK_BYTES)
            if not chunk:
                break
            written += len(chunk)
            if written > remaining_bytes:
                destination.unlink(missing_ok=True)
                raise ProvisioningError(
                    f"archive member {info.filename!r} expanded past its declared "
                    f"size and exceeded the expansion cap after {written} bytes"
                )
            handle.write(chunk)
    return written


def install_archive(
    archive_path: Path,
    target: Path,
    *,
    model: str = "rife-v4.6",
    expected_binary_sha256: str = str(RIFE_RELEASE["binary_sha256"]),
    expected_model_hashes: dict[str, str] | None = None,
    max_expanded_bytes: int = MAX_EXPANDED_BYTES,
) -> InstallReport:
    """Verify, stage, verify again, then swap into ``target`` atomically.

    The install is only visible at ``target`` once every digest has matched in
    the staging directory, so an interrupted or failed install leaves whatever
    was already installed exactly as it was.
    """
    if not archive_path.is_file():
        raise ProvisioningError(f"archive not found: {archive_path}")
    # Overridable so the tests can drive the real code path with a small
    # synthetic archive. Nothing in the shipped commands passes it, so a real
    # install is always checked against the pinned digests.
    pinned_hashes = (
        dict(PINNED_MODELS[model].file_hashes)
        if expected_model_hashes is None
        else dict(expected_model_hashes)
    )

    staging = target.parent / f".{target.name}.staging.{os.getpid()}"
    backup = target.parent / f".{target.name}.previous.{os.getpid()}"
    if staging.exists():  # pragma: no cover - previous crash in the same pid
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    installed: list[str] = []
    try:
        try:
            archive = zipfile.ZipFile(archive_path)
        except zipfile.BadZipFile as exc:
            raise ProvisioningError(f"{archive_path} is not a readable zip archive: {exc}") from exc
        with archive:
            binary_members, weight_members = _selected_members(
                archive, model=model, expected_files=tuple(sorted(pinned_hashes))
            )
            budget = max_expanded_bytes
            binary_target = staging / BINARY_NAME
            budget -= _extract_bounded(
                archive, binary_members[0], binary_target, remaining_bytes=budget
            )
            binary_target.chmod(binary_target.stat().st_mode | stat.S_IXUSR | stat.S_IRUSR)
            installed.append(BINARY_NAME)
            for info in weight_members:
                name = Path(info.filename).name
                weight_target = staging / model / name
                budget -= _extract_bounded(archive, info, weight_target, remaining_bytes=budget)
                installed.append(f"{model}/{name}")

        actual_binary = sha256_file(str(staging / BINARY_NAME)).removeprefix("sha256:")
        if actual_binary != expected_binary_sha256:
            raise ProvisioningError(
                f"the extracted executable does not match the pinned digest: "
                f"expected sha256:{expected_binary_sha256}, found sha256:{actual_binary}. "
                "Nothing was installed."
            )
        for filename, expected_digest in sorted(pinned_hashes.items()):
            found = sha256_file(str(staging / model / filename)).removeprefix("sha256:")
            if found != expected_digest:
                raise ProvisioningError(
                    f"extracted {model}/{filename} does not match its pinned digest: "
                    f"expected sha256:{expected_digest}, found sha256:{found}. "
                    "Nothing was installed."
                )

        replaced = target.exists()
        target.parent.mkdir(parents=True, exist_ok=True)
        if replaced:
            os.replace(target, backup)
        try:
            os.replace(staging, target)
        except OSError as exc:  # pragma: no cover - filesystem specific
            if replaced:
                os.replace(backup, target)
            raise ProvisioningError(f"could not install into {target}: {exc}") from exc
        return InstallReport(
            target=target,
            archive_path=archive_path,
            archive_bytes=archive_path.stat().st_size,
            installed_files=tuple(installed),
            binary_verified=True,
            model_verified=True,
            replaced_existing=replaced,
            notes=(
                "every digest was verified in a staging directory before the "
                "existing install was touched",
                "no downloaded byte was executed during provisioning",
            ),
        )
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)


def provision(
    *,
    root: Path | None = None,
    model: str = "rife-v4.6",
    work_dir: Path | None = None,
    transport: Transport = default_transport,
    keep_archive: bool = False,
    max_bytes: int = MAX_ARCHIVE_BYTES,
    timeout_seconds: float = DOWNLOAD_TIMEOUT_SECONDS,
) -> InstallReport:
    """Download and install the pinned release into the runtime root.

    Explicit by construction: nothing calls this except the ``runtime fetch
    --install`` command an operator types.
    """
    base = root if root is not None else default_runtime_root()
    target = base / DIRECTORY_NAME
    staging_dir = work_dir if work_dir is not None else base / ".download"
    archive_path = staging_dir / "rife-ncnn-vulkan-pinned.zip"
    try:
        download_archive(
            str(RIFE_RELEASE["source_url"]),
            archive_path,
            expected_sha256=str(RIFE_RELEASE["archive_sha256"]),
            max_bytes=max_bytes,
            timeout_seconds=timeout_seconds,
            transport=transport,
        )
        report = install_archive(archive_path, target, model=model)
    finally:
        if not keep_archive:
            archive_path.unlink(missing_ok=True)
    return report


def installed_runtime(root: Path | None = None) -> RifeRuntime:
    """The runtime as it now stands, for reporting after an install."""
    return RifeRuntime.discover(root)
