"""Content-address local Diffusers snapshots without importing a model runtime."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Annotated

from pydantic import Field

from animalite.contracts.base import Contract, Document
from animalite.errors import ValidationRejected

COMPONENTS = ("scheduler", "text_encoder", "tokenizer", "transformer", "vae")
DATA_SUFFIXES = {".safetensors", ".json", ".model", ".txt", ".tiktoken"}
Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class Snapshot(Contract):
    directory: Path
    digest: Digest


class ModelBundle(Document):
    ltx: Snapshot
    wan: Snapshot


def snapshot_digest(root: Path, copy_to: Path | None = None) -> str:
    """Hash paths and contents of exactly the files exposed to the model loader."""
    files = [Path("model_index.json")]
    for component in COMPONENTS:
        folder = root / component
        if not folder.is_dir():
            raise ValidationRejected(f"missing model component: {folder}")
        if not any(folder.iterdir()):
            raise ValidationRejected(f"empty model component: {folder}")
        for source in folder.rglob("*"):
            if source.is_dir():
                continue
            if source.suffix not in DATA_SUFFIXES or not source.is_file():
                raise ValidationRejected(f"unexpected file in local model snapshot: {source}")
            files.append(source.relative_to(root))
    tree = hashlib.sha256()
    for path in sorted(files):
        digest = hashlib.sha256()
        with (root / path).open("rb") as src:
            if copy_to is None:
                digest = hashlib.file_digest(src, "sha256")
            else:
                dest = copy_to / path
                dest.parent.mkdir(exist_ok=True, parents=True)
                with dest.open("xb") as out:
                    while block := src.read(1024 * 1024):
                        digest.update(block)
                        out.write(block)
        tree.update(path.as_posix().encode() + b"\0" + digest.digest())
    return "sha256:" + tree.hexdigest()


def configured_bundle() -> ModelBundle | None:
    path = os.environ.get("ANIMALITE_LTX_WAN_BUNDLE")
    if not path:
        return None
    bundle = ModelBundle.model_validate_json(Path(path).read_bytes())
    if not all(s.directory.is_absolute() for s in (bundle.ltx, bundle.wan)):
        raise ValidationRejected("model bundle requires absolute snapshot directories")
    return bundle
