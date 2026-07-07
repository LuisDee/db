"""Time-to-full capacity estimation via simple linear extrapolation.

Unit-agnostic on purpose: the caller picks whatever "used" unit its
history is already in (bytes, percent, rows -- doesn't matter) and
passes a matching `capacity` in the same unit. For Check_MK filesystem
history (checkmk.filesystem_history) that's `used_percent` against
`capacity=100.0`; for a byte-denominated series it's raw bytes against
the filesystem/tablespace size. No engine-specific knowledge lives
here -- this is pure arithmetic, fully unit-testable with hand-crafted
series (see tests/test_capacity.py), independent of whether any real
Check_MK/DB instance is available.

Deliberately simple (per playbook-disk-space.md's brief: "slope of a
linear fit is enough -- don't over-engineer"): an ordinary least-squares
fit of used-vs-time, projected forward. No seasonality, no outlier
rejection, no confidence intervals.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence


@dataclass(frozen=True)
class CapacityEstimate:
    growth_per_second: float
    time_to_full: timedelta | None


def linear_growth_rate(history: Sequence[tuple[datetime, float]]) -> float | None:
    """Least-squares slope of `used` against elapsed seconds, in
    units-per-second. None when there's not enough information to fit a
    line at all (fewer than two points, or every point at the same
    timestamp) -- never a division-by-zero crash.
    """
    if len(history) < 2:
        return None

    ordered = sorted(history, key=lambda point: point[0])
    t0 = ordered[0][0]
    xs = [(t - t0).total_seconds() for t, _ in ordered]
    ys = [used for _, used in ordered]

    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)

    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    denominator = sum((x - x_mean) ** 2 for x in xs)

    if denominator == 0:
        return None  # every sample at the same timestamp -- no time axis to fit

    return numerator / denominator


def estimate_time_to_full(
    history: Sequence[tuple[datetime, float]], capacity: float
) -> CapacityEstimate | None:
    """Project `history` forward to `capacity` at its linear growth
    rate. Returns None only when there isn't enough data to fit a
    trend at all; a flat or decreasing trend still returns a
    CapacityEstimate (so the caller can see the growth rate), but with
    `time_to_full=None` rather than an infinite or nonsensical value --
    "never fills up at this rate" is not a timestamp.
    """
    rate = linear_growth_rate(history)
    if rate is None:
        return None

    if rate <= 0:
        return CapacityEstimate(growth_per_second=rate, time_to_full=None)

    latest_used = sorted(history, key=lambda point: point[0])[-1][1]
    remaining = capacity - latest_used
    if remaining <= 0:
        return CapacityEstimate(growth_per_second=rate, time_to_full=timedelta(0))

    return CapacityEstimate(
        growth_per_second=rate, time_to_full=timedelta(seconds=remaining / rate)
    )
