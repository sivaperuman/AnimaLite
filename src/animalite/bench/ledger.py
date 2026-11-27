"""Append-only benchmark run ledger with tamper detection.

Section 12.0: "a timeout or invalid output fails the sample and remains in the
ledger" and "Retuning requires a new profile revision and complete rerun, not
deletion of weak cases."

Two mechanisms enforce that:

1. **Declared plan.** The plan lists every run before timing starts. A run id
   with no record is a *missing observation*, which blocks qualification.
2. **Hash chain.** Each ledger line carries the digest of the previous line and
   its own digest. Deleting, reordering or editing a line breaks the chain, and
   :meth:`RunLedger.verify` reports exactly where.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

from animalite.contracts.base import canonical_json
from animalite.contracts.benchmark import BenchmarkPlan, PlannedRun, RunRecord
from animalite.errors import LedgerIntegrityError

__all__ = ["LedgerVerification", "RunLedger"]

_GENESIS = "sha256:" + "0" * 64


def _chain_digest(previous: str, record: RunRecord) -> str:
    payload = previous.encode("utf-8") + b"\n" + canonical_json(record)
    return "sha256:" + hashlib.sha256(payload).hexdigest()


class LedgerVerification:
    """Result of verifying a ledger against its plan."""

    def __init__(
        self,
        *,
        ok: bool,
        head_digest: str,
        record_count: int,
        problems: list[str],
        missing_run_ids: list[str],
        unplanned_run_ids: list[str],
    ) -> None:
        self.ok = ok
        self.head_digest = head_digest
        self.record_count = record_count
        self.problems = problems
        self.missing_run_ids = missing_run_ids
        self.unplanned_run_ids = unplanned_run_ids

    def __bool__(self) -> bool:
        return self.ok


class RunLedger:
    """Append-only JSONL ledger for one benchmark plan."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    @property
    def plan_path(self) -> Path:
        return self.directory / "plan.json"

    @property
    def runs_path(self) -> Path:
        return self.directory / "runs.jsonl"

    # ------------------------------------------------------------------- writing

    def write_plan(self, plan: BenchmarkPlan) -> Path:
        if self.plan_path.exists():
            raise LedgerIntegrityError(
                f"plan already exists at {self.plan_path}; a new plan needs a new "
                "ledger directory so earlier runs are not silently replaced"
            )
        self.plan_path.write_text(
            json.dumps(plan.to_json_obj(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return self.plan_path

    def read_plan(self) -> BenchmarkPlan:
        return BenchmarkPlan.model_validate_json(self.plan_path.read_text(encoding="utf-8"))

    def append(self, record: RunRecord) -> str:
        """Append one run record and return the new head digest."""
        previous = self.head_digest()
        digest = _chain_digest(previous, record)
        line = json.dumps(
            {"prev": previous, "digest": digest, "record": record.to_json_obj()},
            sort_keys=True,
        )
        with self.runs_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
        return digest

    # ------------------------------------------------------------------- reading

    def _raw_lines(self) -> Iterator[dict[str, object]]:
        if not self.runs_path.exists():
            return
        with self.runs_path.open(encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise LedgerIntegrityError(
                        f"{self.runs_path}:{number} is not valid JSON: {exc}"
                    ) from exc
                yield payload

    def records(self) -> list[RunRecord]:
        return [RunRecord.model_validate(p["record"]) for p in self._raw_lines()]

    def head_digest(self) -> str:
        digest = _GENESIS
        for payload in self._raw_lines():
            digest = str(payload["digest"])
        return digest

    # ---------------------------------------------------------------- verifying

    def verify(self, plan: BenchmarkPlan | None = None) -> LedgerVerification:
        """Recompute the chain and compare recorded runs against the plan."""
        problems: list[str] = []
        previous = _GENESIS
        seen: list[str] = []
        count = 0

        for number, payload in enumerate(self._raw_lines(), start=1):
            count += 1
            try:
                record = RunRecord.model_validate(payload["record"])
            except Exception as exc:
                problems.append(f"line {number}: record does not validate: {exc}")
                continue
            if payload.get("prev") != previous:
                problems.append(
                    f"line {number} ({record.run_id}): previous digest "
                    f"{payload.get('prev')!r} does not match the computed chain "
                    f"{previous!r}; a record was removed, reordered or edited"
                )
            expected = _chain_digest(previous, record)
            if payload.get("digest") != expected:
                problems.append(
                    f"line {number} ({record.run_id}): digest {payload.get('digest')!r} "
                    f"does not match the record content ({expected!r}); the record was "
                    "edited after it was written"
                )
            previous = str(payload.get("digest", expected))
            seen.append(record.run_id)

        duplicates = sorted({rid for rid in seen if seen.count(rid) > 1})
        if duplicates:
            problems.append(f"duplicate run records for run_id(s): {duplicates}")

        missing: list[str] = []
        unplanned: list[str] = []
        resolved_plan = plan
        if resolved_plan is None and self.plan_path.exists():
            resolved_plan = self.read_plan()
        if resolved_plan is not None:
            planned = resolved_plan.run_ids()
            missing = sorted(planned - set(seen))
            unplanned = sorted(set(seen) - planned)
            if missing:
                problems.append(
                    f"{len(missing)} planned run(s) have no record: {missing[:8]}"
                    + (" ..." if len(missing) > 8 else "")
                )
            if unplanned:
                problems.append(f"records for unplanned run_id(s): {unplanned[:8]}")

        return LedgerVerification(
            ok=not problems,
            head_digest=previous,
            record_count=count,
            problems=problems,
            missing_run_ids=missing,
            unplanned_run_ids=unplanned,
        )

    def missing_runs(self, plan: BenchmarkPlan) -> list[PlannedRun]:
        recorded = {r.run_id for r in self.records()}
        return [r for r in plan.planned_runs if r.run_id not in recorded]
