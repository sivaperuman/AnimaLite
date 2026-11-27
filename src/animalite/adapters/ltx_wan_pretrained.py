"""Pinned public Diffusers checkpoints for the optional research profile."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from importlib import import_module
from pathlib import Path

from animalite.adapters.ltx_wan_bundle import COMPONENTS, ModelBundle, Snapshot, snapshot_digest
from animalite.errors import ValidationRejected


@dataclass(frozen=True)
class Checkpoint:
    repository: str
    revision: str
    digest: str
    size_bytes: int


# Tree hashes use snapshot_digest's path + SHA-256 format. File content hashes
# came from the pinned Git LFS records or verified, ordinary Git blob contents.
CHECKPOINTS = {
    "ltx": Checkpoint(
        "Lightricks/LTX-Video-0.9.5",
        "e58e28c39631af4d1468ee57a853764e11c1d37e",
        "sha256:5274674e388b5fe75e12e274f23ad500cd9cb6f57c5efc7abf820a07d33c686d",
        25_390_818_694,
    ),
    "wan": Checkpoint(
        "Wan-AI/Wan2.1-VACE-1.3B-diffusers",
        "ec4d2cb062b548996b179d493fdd05340de702a1",
        "sha256:c09f585bfad3ba2faf659f889a3d898fd43ac0fdb258b83c0385614ea45c9dd1",
        19_037_105_642,
    ),
}


def pretrained_plan() -> dict[str, object]:
    sizes = [item.size_bytes for item in CHECKPOINTS.values()]
    return {
        "checkpoints": {stage: asdict(item) for stage, item in CHECKPOINTS.items()},
        "snapshot_bytes": sum(sizes),
        "additional_worker_copy_bytes": max(sizes),
    }


def fetch_pretrained(cache: Path | None) -> ModelBundle:
    try:
        download = import_module("huggingface_hub").snapshot_download
    except ImportError as exc:
        raise ValidationRejected("install the neural extra before fetching checkpoints") from exc
    selected = {}
    for stage, item in CHECKPOINTS.items():
        try:
            path = Path(
                download(
                    item.repository,
                    revision=item.revision,
                    cache_dir=cache,
                    allow_patterns=["model_index.json", *(f"{name}/*" for name in COMPONENTS)],
                    max_workers=2,
                )
            ).resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ValidationRejected(f"could not fetch the pinned {stage} snapshot: {exc}") from exc
        if snapshot_digest(path) != item.digest:
            raise ValidationRejected(
                f"{stage} snapshot differs from the pinned pretrained checkpoint"
            )
        selected[stage] = Snapshot(directory=path, digest=item.digest)
    return ModelBundle(ltx=selected["ltx"], wan=selected["wan"])
