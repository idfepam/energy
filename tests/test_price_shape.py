"""Tests for the cross-zone price-shape metrics."""

from __future__ import annotations

import numpy as np
import pandas as pd

from energy_collect.price_shape import (
    alignment,
    amplitude_ratio,
    calendar_profile,
    cumulative_negative_hours,
    distribution_metrics,
    duration_curve,
)


def _hours(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")


def test_relative_profile_is_level_free() -> None:
    idx = _hours(24 * 14)
    shape = 1 + 0.5 * np.sin(2 * np.pi * idx.hour / 24)
    panel = pd.DataFrame({"low": 20 * shape, "high": 200 * shape}, index=idx)
    prof = calendar_profile(panel, "hod")
    assert prof.shape == (24, 2)
    np.testing.assert_allclose(prof["low"], prof["high"])
    np.testing.assert_allclose(prof.mean(), 1.0)


def test_quarter_profile_has_four_groups() -> None:
    idx = pd.date_range("2025-01-01", "2025-12-31 23:00", freq="h", tz="UTC")
    panel = pd.DataFrame({"z": np.where(idx.quarter == 3, 2.0, 1.0)}, index=idx)
    prof = calendar_profile(panel, "quarter", relative=False)
    assert prof["z"].tolist() == [1.0, 1.0, 2.0, 1.0]


def test_alignment_ignores_level_and_scale() -> None:
    base = np.sin(np.linspace(0, 2 * np.pi, 24))
    assert abs(alignment(5 + 3 * base, base) - 1.0) < 1e-12
    assert alignment(-base, base) < -0.99
    assert np.isnan(alignment(np.ones(24), base))


def test_amplitude_ratio() -> None:
    base = np.sin(np.linspace(0, 2 * np.pi, 24))
    assert abs(amplitude_ratio(0.5 * base, base) - 0.5) < 1e-12
    assert abs(amplitude_ratio(2 * base + 7, base) - 2.0) < 1e-12


def test_distribution_metrics_counts_tails() -> None:
    idx = _hours(48)
    values = np.full(48, 50.0)
    values[[1, 2, 3]] = -10.0  # three negative hours on day one
    values[5] = 0.5  # near zero
    values[30] = 250.0  # spike on day two
    m = distribution_metrics(pd.Series(values, index=idx))
    assert m["negative_hours"] == 3
    assert abs(m["near_zero_share"] - 1 / 48) < 1e-12
    assert m["spike_hours"] == 1
    assert m["lowest"] == -10.0 and m["peak"] == 250.0
    # day one spread 60, day two spread 200
    assert abs(m["daily_spread"] - 130.0) < 1e-12
    assert m["floor_at_zero"] is False


def test_floor_at_zero_detected() -> None:
    s = pd.Series([0.0, 10.0, 20.0, 0.0], index=_hours(4))
    assert distribution_metrics(s)["floor_at_zero"] is True


def test_cumulative_negative_hours_by_day() -> None:
    idx = _hours(72)
    values = np.ones(72)
    values[[0, 1]] = -1  # day 1: two
    values[50] = -1  # day 3: one
    cum = cumulative_negative_hours(pd.DataFrame({"z": values}, index=idx))
    assert cum["z"].tolist() == [2, 2, 3]


def test_duration_curve_descending_endpoints() -> None:
    s = pd.Series(np.arange(1000, dtype=float), index=_hours(1000))
    curve = duration_curve(s, points=11)
    assert len(curve) == 11
    assert curve[0] == 999.0 and curve[-1] == 0.0
    assert all(a >= b for a, b in zip(curve, curve[1:]))
