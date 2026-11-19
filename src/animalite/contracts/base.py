"""Shared base types for AnimaLite's versioned, JSON-compatible contracts.

Every contract document is:

* **versioned** -- top-level documents carry ``schema_version``;
* **closed** -- unknown fields are rejected rather than silently ignored
  (handoff v0.2 section 4.2);
* **canonically serializable** -- :func:`canonical_json` produces byte-stable
  output so output-affecting settings can be hashed and compared.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict

from animalite import SCHEMA_VERSION

__all__ = [
    "SCHEMA_VERSION",
    "Contract",
    "Document",
    "canonical_json",
    "content_digest",
    "sha256_file",
]

_HASH_PREFIX = "sha256:"


class Contract(BaseModel):
    """Base for every AnimaLite contract value object.

    ``extra="forbid"`` implements the "unknown critical fields must not be
    silently ignored" rule: an unrecognized key is a validation error, not a
    dropped field. ``frozen=True`` keeps job/attempt records immutable once
    built, which is what the attempt store relies on.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        validate_default=True,
        str_strip_whitespace=True,
    )

    def to_json_obj(self) -> dict[str, Any]:
        """Return a plain JSON-compatible dict (enums as values, paths as str)."""
        obj = self.model_dump(mode="json")
        if not isinstance(obj, dict):  # pragma: no cover - pydantic guarantees dict
            raise TypeError("contract did not serialize to an object")
        return obj


class Document(Contract):
    """A contract that is written to disk on its own and therefore versioned."""

    schema_version: str = SCHEMA_VERSION


_T = TypeVar("_T", bound=Contract)


def canonical_json(value: Contract | dict[str, Any]) -> bytes:
    """Serialize to canonical JSON bytes: sorted keys, compact, UTF-8, no NaN.

    Byte stability matters because settings digests are compared across runs and
    across hosts; ``json.dumps`` defaults (spaces, insertion order) are not
    stable enough for that.
    """
    obj = value.to_json_obj() if isinstance(value, Contract) else value
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def content_digest(value: Contract | dict[str, Any]) -> str:
    """Return ``sha256:<hex>`` over :func:`canonical_json` of ``value``."""
    return _HASH_PREFIX + hashlib.sha256(canonical_json(value)).hexdigest()


def sha256_file(path: str, *, chunk_size: int = 1024 * 1024) -> str:
    """Return ``sha256:<hex>`` of a file, read in bounded chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return _HASH_PREFIX + digest.hexdigest()
