"""Percentile behaviour, including the planned 36/12 sample sizes."""

from __future__ import annotations

import math

import pytest

from animalite.bench.stats import (
    maximum,
    median,
    nearest_rank_index,
    nearest_rank_percentile,
    summarize,
)


@pytest.mark.parametrize(
    ("n", "expected"),
    [
        (1, 1),
        (2, 2),
        (3, 3),
        (10, 10),
        (12, 12),  # section 12.0: one process-cold run per clip -> p95 is the maximum
        (20, 19),
        (21, 20),
        (36, 35),  # section 12.0: three warm runs per clip -> the 35th observation
        (40, 38),
        (100, 95),
    ],
)
def test_nearest_rank_index_matches_ceil_of_095n(n, expected):
    assert nearest_rank_index(n) == expected
    assert nearest_rank_index(n) == max(1, min(n, math.ceil(0.95 * n)))


def test_p95_of_the_36_run_warm_sample_selects_the_35th_sorted_value():
    values = [float(i) for i in range(1, 37)]
    assert nearest_rank_percentile(values) == (35.0, 35)


def test_p95_of_the_12_run_cold_sample_is_the_maximum():
    values = [float(i) for i in range(1, 13)]
    result = nearest_rank_percentile(values)
    assert result is not None
    value, index = result
    assert index == 12
    assert value == max(values) == 12.0


def test_percentile_sorts_before_indexing():
    values = [9.0, 1.0, 5.0, 3.0, 7.0]
    assert nearest_rank_percentile(values) == (9.0, 5)


def test_empty_sample_has_no_statistics_rather_than_zero():
    assert nearest_rank_percentile([]) is None
    assert median([]) is None
    assert maximum([]) is None
    summary = summarize([])
    assert summary["n"] == 0
    assert summary["median"] is None
    assert summary["percentile"] is None
    assert summary["maximum"] is None


def test_single_observation_reports_itself():
    assert nearest_rank_percentile([4.2]) == (4.2, 1)
    assert median([4.2]) == 4.2


def test_median_is_the_middle_value_or_the_mean_of_two():
    assert median([1.0, 2.0, 3.0]) == 2.0
    assert median([1.0, 2.0, 3.0, 4.0]) == 2.5
    assert median([3.0, 1.0, 2.0]) == 2.0


def test_invalid_inputs_are_rejected():
    with pytest.raises(ValueError, match="n >= 1"):
        nearest_rank_index(0)
    with pytest.raises(ValueError, match="percentile must be in"):
        nearest_rank_index(10, 0.0)
    with pytest.raises(ValueError, match="percentile must be in"):
        nearest_rank_index(10, 1.5)


def test_summarize_reports_the_sorted_index_used():
    values = [float(i) for i in range(1, 37)]
    summary = summarize(values)
    assert summary["percentile_sorted_index"] == 35
    assert summary["percentile"] == 35.0
    assert summary["maximum"] == 36.0
    assert summary["minimum"] == 1.0
