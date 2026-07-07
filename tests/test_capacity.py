from datetime import datetime, timedelta, timezone

import pytest

from dba_agent.capacity import CapacityEstimate, estimate_time_to_full, linear_growth_rate


def _series(base: datetime, hours_and_values: list[tuple[float, float]]):
    return [(base + timedelta(hours=h), v) for h, v in hours_and_values]


BASE = datetime(2026, 7, 1, tzinfo=timezone.utc)


def test_linear_growth_rate_positive_slope():
    history = _series(BASE, [(0, 0), (1, 3600), (2, 7200)])  # 1 unit/sec
    rate = linear_growth_rate(history)
    assert rate == pytest.approx(1.0, rel=1e-6)


def test_linear_growth_rate_negative_slope():
    history = _series(BASE, [(0, 100), (1, 50), (2, 0)])
    rate = linear_growth_rate(history)
    assert rate < 0


def test_linear_growth_rate_flat_series_is_zero():
    history = _series(BASE, [(0, 42), (1, 42), (2, 42)])
    assert linear_growth_rate(history) == pytest.approx(0.0, abs=1e-9)


def test_linear_growth_rate_needs_at_least_two_points():
    assert linear_growth_rate([]) is None
    assert linear_growth_rate([(BASE, 10)]) is None


def test_linear_growth_rate_all_same_timestamp_is_none():
    assert linear_growth_rate([(BASE, 1), (BASE, 5)]) is None


def test_estimate_time_to_full_on_growing_series():
    # used goes 0 -> 3600 -> 7200 over 2 hours: 1 unit/sec growth.
    history = _series(BASE, [(0, 0), (1, 3600), (2, 7200)])
    estimate = estimate_time_to_full(history, capacity=36000)

    assert isinstance(estimate, CapacityEstimate)
    assert estimate.growth_per_second == pytest.approx(1.0, rel=1e-6)
    # latest used = 7200, remaining = 36000 - 7200 = 28800 units, at 1/s => 28800s
    assert estimate.time_to_full.total_seconds() == pytest.approx(28800, rel=1e-6)


def test_estimate_time_to_full_flat_series_returns_no_estimate():
    history = _series(BASE, [(0, 50), (1, 50), (2, 50)])
    estimate = estimate_time_to_full(history, capacity=100)

    assert estimate is not None  # we still report the (zero) growth rate
    assert estimate.growth_per_second == pytest.approx(0.0, abs=1e-9)
    assert estimate.time_to_full is None


def test_estimate_time_to_full_decreasing_series_returns_no_estimate():
    history = _series(BASE, [(0, 100), (1, 50), (2, 0)])
    estimate = estimate_time_to_full(history, capacity=100)

    assert estimate.growth_per_second < 0
    assert estimate.time_to_full is None


def test_estimate_time_to_full_insufficient_data_returns_none():
    assert estimate_time_to_full([], capacity=100) is None
    assert estimate_time_to_full([(BASE, 10)], capacity=100) is None


def test_estimate_time_to_full_already_at_or_past_capacity_is_zero():
    history = _series(BASE, [(0, 90), (1, 95), (2, 100)])
    estimate = estimate_time_to_full(history, capacity=100)

    assert estimate.time_to_full == timedelta(0)


def test_estimate_time_to_full_already_past_capacity_is_zero_not_negative():
    history = _series(BASE, [(0, 90), (1, 100), (2, 110)])
    estimate = estimate_time_to_full(history, capacity=100)

    assert estimate.time_to_full == timedelta(0)
