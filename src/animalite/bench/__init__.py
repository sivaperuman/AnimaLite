"""Benchmark harness: plan, ledger, statistics and the eligibility evaluator."""

from __future__ import annotations

from animalite.bench.evaluate import build_report, distributions_for, evaluate_eligibility
from animalite.bench.ledger import LedgerVerification, RunLedger
from animalite.bench.runner import BenchmarkRunner, build_plan, load_dataset, load_host_record
from animalite.bench.stats import (
    maximum,
    median,
    nearest_rank_index,
    nearest_rank_percentile,
    summarize,
)

__all__ = [
    "BenchmarkRunner",
    "LedgerVerification",
    "RunLedger",
    "build_plan",
    "build_report",
    "distributions_for",
    "evaluate_eligibility",
    "load_dataset",
    "load_host_record",
    "maximum",
    "median",
    "nearest_rank_index",
    "nearest_rank_percentile",
    "summarize",
]
