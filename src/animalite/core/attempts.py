"""Attempt-owned directories and immutable attempt records.

Layout for one attempt::

    <workspace>/attempts/<attempt_id>/
        attempt.json        the record, rewritten only while the attempt runs
        work/               attempt-owned scratch; the encoder writes here
        output/             published output; created only on success
        logs/attempt.jsonl  structured stage log
        diagnostics/        retained on failure (encoder stderr, partial file info)

Rules enforced here (handoff rule 5):

* an attempt directory is never reused;
* output is published by atomic rename from ``work/`` into ``output/``;
* a published output is never overwritten -- a retry gets a new attempt;
* approved inputs are never written to.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path

from animalite.contracts.job import AttemptRecord
from animalite.errors import AttemptConflictError

__all__ = ["AttemptDirs", "AttemptStore", "new_attempt_id"]


def new_attempt_id(prefix: str = "att") -> str:
    """Sortable, collision-resistant attempt id: ``att-<utc>-<random>``."""
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
    return f"{prefix}-{stamp}-{secrets.token_hex(4)}"


class AttemptDirs:
    """The four directories owned by one attempt."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.work = root / "work"
        self.output = root / "output"
        self.logs = root / "logs"
        self.diagnostics = root / "diagnostics"

    def create(self) -> AttemptDirs:
        if self.root.exists():
            raise AttemptConflictError(
                f"attempt directory already exists and is immutable: {self.root}"
            )
        for path in (self.root, self.work, self.logs):
            path.mkdir(parents=True)
        return self

    @property
    def record_path(self) -> Path:
        return self.root / "attempt.json"

    @property
    def log_path(self) -> Path:
        return self.logs / "attempt.jsonl"

    def publish(self, produced: Path, filename: str) -> Path:
        """Move a completed file from ``work/`` into ``output/`` atomically.

        ``os.replace`` within one attempt directory is a same-filesystem rename,
        so a reader never sees a half-written published file.
        """
        if not produced.is_file():
            raise AttemptConflictError(f"nothing to publish at {produced}")
        self.output.mkdir(parents=True, exist_ok=True)
        destination = self.output / filename
        if destination.exists():
            raise AttemptConflictError(
                f"refusing to overwrite published output {destination}; retry creates a "
                "new attempt (handoff rule 5)"
            )
        os.replace(produced, destination)
        return destination

    def retain_diagnostics(self) -> Path:
        self.diagnostics.mkdir(parents=True, exist_ok=True)
        return self.diagnostics


class AttemptStore:
    """Filesystem store for attempt directories and records."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.attempts_root = workspace / "attempts"

    def allocate(self, attempt_id: str) -> AttemptDirs:
        return AttemptDirs(self.attempts_root / attempt_id).create()

    def dirs(self, attempt_id: str) -> AttemptDirs:
        return AttemptDirs(self.attempts_root / attempt_id)

    def save(self, record: AttemptRecord) -> Path:
        """Write the attempt record, atomically replacing the in-progress copy.

        Terminal records are written once and then refuse further writes, which
        is what keeps a completed attempt immutable.
        """
        dirs = self.dirs(record.attempt_id)
        path = dirs.record_path
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            existing_state = existing.get("state")
            if existing_state in {"succeeded", "failed", "cancelled"}:
                raise AttemptConflictError(
                    f"attempt {record.attempt_id} is already terminal "
                    f"({existing_state}); records are immutable"
                )
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(record.to_json_obj(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, path)
        return path

    def load(self, attempt_id: str) -> AttemptRecord:
        path = self.dirs(attempt_id).record_path
        return AttemptRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def list_attempt_ids(self) -> list[str]:
        if not self.attempts_root.is_dir():
            return []
        return sorted(p.name for p in self.attempts_root.iterdir() if p.is_dir())
