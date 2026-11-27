"""Bounded provisioning: what it refuses, and what it leaves behind when it does.

Every test here uses a synthetic archive of a few hundred bytes and a fake
transport. None needs the 431 MB release, the network, or real weights -- and
none executes a downloaded byte, which is the property the whole module exists
to preserve.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from contextlib import contextmanager
from pathlib import Path

import pytest

from animalite.adapters.rife_provision import (
    ProvisioningError,
    download_archive,
    install_archive,
)
from animalite.adapters.rife_runtime import BINARY_NAME

MODEL = "test-model"
_BINARY_BYTES = b"#!/bin/sh\necho pinned\n"
_WEIGHT_BYTES = {"flownet.param": b"7767517 layers\n", "flownet.bin": b"\x00\x01\x02\x03" * 16}

BINARY_SHA = hashlib.sha256(_BINARY_BYTES).hexdigest()
WEIGHT_SHA = {name: hashlib.sha256(data).hexdigest() for name, data in _WEIGHT_BYTES.items()}


def _archive(
    path: Path,
    *,
    binary: bytes = _BINARY_BYTES,
    weights: dict[str, bytes] | None = None,
    extra: list[tuple[str, bytes, int]] | None = None,
    root: str = "rife-ncnn-vulkan-20221029-ubuntu",
) -> Path:
    """A minimal stand-in for the release archive."""
    contents = _WEIGHT_BYTES if weights is None else weights
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{root}/{BINARY_NAME}", binary)
        for name, data in contents.items():
            archive.writestr(f"{root}/{MODEL}/{name}", data)
        for name, data, mode in extra or []:
            info = zipfile.ZipInfo(name)
            info.external_attr = mode << 16
            archive.writestr(info, data)
    return path


def _install(archive: Path, target: Path, **kwargs):
    return install_archive(
        archive,
        target,
        model=MODEL,
        expected_binary_sha256=kwargs.pop("expected_binary_sha256", BINARY_SHA),
        expected_model_hashes=kwargs.pop("expected_model_hashes", WEIGHT_SHA),
        **kwargs,
    )


def _transport(payload: bytes):
    @contextmanager
    def opener(url: str):
        yield io.BytesIO(payload)

    return opener


# --- download bounds ----------------------------------------------------------


def test_a_digest_mismatch_deletes_the_download_and_extracts_nothing(tmp_path):
    """Verification happens before extraction, so a tampered archive cannot land.

    The partial file is removed too: leaving it behind invites the next run to
    treat a bad archive as a cached download.
    """
    destination = tmp_path / "rife.zip"
    with pytest.raises(ProvisioningError, match="digest mismatch"):
        download_archive(
            "https://example.invalid/rife.zip",
            destination,
            expected_sha256="0" * 64,
            transport=_transport(b"tampered payload"),
        )
    assert not destination.exists()


def test_a_truncated_download_is_a_digest_mismatch(tmp_path):
    payload = b"the full archive bytes"
    destination = tmp_path / "rife.zip"
    with pytest.raises(ProvisioningError, match="digest mismatch"):
        download_archive(
            "https://example.invalid/rife.zip",
            destination,
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            transport=_transport(payload[:5]),
        )
    assert not destination.exists()


def test_an_oversized_download_is_stopped_at_the_cap(tmp_path):
    destination = tmp_path / "rife.zip"
    with pytest.raises(ProvisioningError, match="byte cap"):
        download_archive(
            "https://example.invalid/rife.zip",
            destination,
            expected_sha256="0" * 64,
            max_bytes=16,
            transport=_transport(b"x" * 4096),
        )
    assert not destination.exists()


def test_a_verified_download_is_kept(tmp_path):
    payload = b"exactly these bytes"
    destination = tmp_path / "rife.zip"
    download_archive(
        "https://example.invalid/rife.zip",
        destination,
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        transport=_transport(payload),
    )
    assert destination.read_bytes() == payload


# --- archive safety -----------------------------------------------------------


def test_a_traversal_member_is_refused(tmp_path):
    archive = _archive(tmp_path / "a.zip", extra=[("../../escaped.txt", b"nope", 0o100644)])
    target = tmp_path / "install"
    with pytest.raises(ProvisioningError, match="escapes the install directory"):
        _install(archive, target)
    assert not (tmp_path.parent / "escaped.txt").exists()
    assert not target.exists()


def test_an_absolute_member_is_refused(tmp_path):
    archive = _archive(tmp_path / "a.zip", extra=[("/etc/passwd", b"nope", 0o100644)])
    with pytest.raises(ProvisioningError, match="escapes the install directory"):
        _install(archive, tmp_path / "install")


def test_a_symlink_member_is_refused(tmp_path):
    """A zip symlink can point anywhere; extracting one hands over the filesystem."""
    archive = _archive(tmp_path / "a.zip", extra=[("link", b"/etc/shadow", 0o120777)])
    with pytest.raises(ProvisioningError, match="symbolic link"):
        _install(archive, tmp_path / "install")


def test_an_oversized_expansion_is_refused(tmp_path):
    archive = _archive(tmp_path / "a.zip")
    with pytest.raises(ProvisioningError, match="expansion cap"):
        _install(archive, tmp_path / "install", max_expanded_bytes=4)
    assert not (tmp_path / "install").exists()


def test_an_archive_without_the_executable_is_refused(tmp_path):
    path = tmp_path / "a.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"root/{MODEL}/flownet.param", b"x")
    with pytest.raises(ProvisioningError, match="no 'rife-ncnn-vulkan' executable"):
        _install(path, tmp_path / "install")


def test_an_archive_missing_a_pinned_weight_is_refused(tmp_path):
    archive = _archive(tmp_path / "a.zip", weights={"flownet.param": b"7767517 layers\n"})
    with pytest.raises(ProvisioningError, match="does not contain the pinned"):
        _install(archive, tmp_path / "install")


def test_a_corrupt_zip_is_reported_not_raised_as_a_zip_error(tmp_path):
    path = tmp_path / "a.zip"
    path.write_bytes(b"this is not a zip file")
    with pytest.raises(ProvisioningError, match="not a readable zip archive"):
        _install(path, tmp_path / "install")


# --- installation -------------------------------------------------------------


def test_a_good_archive_installs_the_binary_and_weights(tmp_path):
    archive = _archive(tmp_path / "a.zip")
    target = tmp_path / "install"
    report = _install(archive, target)

    assert report.usable
    assert (target / BINARY_NAME).read_bytes() == _BINARY_BYTES
    assert (target / MODEL / "flownet.bin").read_bytes() == _WEIGHT_BYTES["flownet.bin"]
    assert (target / BINARY_NAME).stat().st_mode & 0o111, "the executable bit was not set"
    assert not report.replaced_existing


def test_only_the_needed_members_are_extracted(tmp_path):
    """An archive does not get to install files nobody asked for."""
    archive = _archive(tmp_path / "a.zip", extra=[("root/unrelated/other.bin", b"junk", 0o100644)])
    target = tmp_path / "install"
    _install(archive, target)
    assert sorted(p.relative_to(target).as_posix() for p in target.rglob("*")) == [
        BINARY_NAME,
        MODEL,
        f"{MODEL}/flownet.bin",
        f"{MODEL}/flownet.param",
    ]


def test_a_tampered_executable_never_reaches_the_install_directory(tmp_path):
    """The digest is checked in staging, so the target is untouched on failure."""
    archive = _archive(tmp_path / "a.zip", binary=b"#!/bin/sh\ntouch /tmp/pwned\n")
    target = tmp_path / "install"
    with pytest.raises(ProvisioningError, match="does not match the pinned digest"):
        _install(archive, target)
    assert not target.exists()
    assert not list(tmp_path.glob(".install.staging*")), "the staging directory was left behind"


def test_a_failed_install_preserves_an_existing_good_one(tmp_path):
    """Verification happens before the existing install is touched."""
    target = tmp_path / "install"
    _install(_archive(tmp_path / "good.zip"), target)
    assert (target / BINARY_NAME).read_bytes() == _BINARY_BYTES

    bad = _archive(tmp_path / "bad.zip", binary=b"tampered")
    with pytest.raises(ProvisioningError):
        _install(bad, target)
    assert (target / BINARY_NAME).read_bytes() == _BINARY_BYTES, (
        "a failed install destroyed the working one"
    )


def test_reinstalling_over_a_good_install_replaces_it_atomically(tmp_path):
    target = tmp_path / "install"
    _install(_archive(tmp_path / "a.zip"), target)
    (target / "stale.txt").write_text("left over from the previous install")

    report = _install(_archive(tmp_path / "b.zip"), target)
    assert report.replaced_existing
    assert not (target / "stale.txt").exists(), "the replacement merged instead of swapping"
    assert (target / BINARY_NAME).read_bytes() == _BINARY_BYTES
    assert not list(tmp_path.glob(".install.previous*")), "the backup was not cleaned up"
