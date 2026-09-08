"""Tests for seasonality and transfer entropy."""

from __future__ import annotations

import numpy as np
import pandas as pd

from energy_collect.seasonality import (
    decompose_zone_series,
    hod_deseasonalize,
    moy_deseasonalize,
    quarter_profile,
)
from energy_collect.transfer_entropy import (
    effective_renyi_transfer_entropy_knn,
    renyi_entropy_knn,
    renyi_transfer_entropy_knn,
    transfer_entropy_discrete,
)


def test_hod_deseasonalize_removes_daily_pattern():
    idx = pd.date_range("2025-01-01", periods=24 * 7, freq="h", tz="UTC")
    values = np.array([float(h % 24) for h in range(len(idx))])
    s = pd.Series(values, index=idx)
    seasonal, residual = hod_deseasonalize(s)
    assert seasonal.std() > 0
    assert residual.std() < seasonal.std()


def test_decompose_zone_series_components():
    idx = pd.date_range("2025-01-01", periods=24 * 14, freq="h", tz="UTC")
    rng = np.random.default_rng(0)
    s = pd.Series(rng.normal(size=len(idx)), index=idx)
    parts = decompose_zone_series(s)
    assert len(parts["residual"]) == len(s)
    assert "seasonal_moy" in parts


def test_moy_deseasonalize_reduces_seasonal_variance():
    idx = pd.date_range("2025-01-01", periods=24 * 365, freq="h", tz="UTC")
    winter = np.where(idx.month.isin([12, 1, 2]), 100.0, 50.0)
    s = pd.Series(winter + np.random.default_rng(1).normal(0, 2, len(idx)), index=idx)
    seasonal, residual = moy_deseasonalize(s)
    assert seasonal.std() > 0
    assert residual.std() < s.std()


def test_quarter_profile_four_values():
    idx = pd.date_range("2025-01-01", periods=24 * 365, freq="h", tz="UTC")
    s = pd.Series(np.linspace(10, 20, len(idx)), index=idx)
    q = quarter_profile(s)
    assert len(q) == 4


def test_renyi_entropy_knn_positive():
    rng = np.random.default_rng(0)
    x = rng.normal(size=(500, 2))
    h = renyi_entropy_knn(x, k=4, alpha=1.0)
    assert h > 0


def test_knn_rte_detects_directed_coupling():
    rng = np.random.default_rng(42)
    n = 3000
    y = rng.normal(size=n)
    x = np.zeros(n)
    for t in range(1, n):
        x[t] = 0.6 * x[t - 1] + 0.6 * y[t - 1] + 0.05 * rng.normal()
    rte = effective_renyi_transfer_entropy_knn(x, y, k=4, alpha=1.0, seed=1)
    rte_rev = effective_renyi_transfer_entropy_knn(y, x, k=4, alpha=1.0, seed=2)
    assert rte > 0.01
    assert rte > rte_rev


def test_transfer_entropy_discrete_positive_for_dependent_series():
    rng = np.random.default_rng(42)
    n = 2000
    y = rng.normal(size=n)
    x = np.zeros(n)
    for t in range(1, n):
        x[t] = 0.7 * x[t - 1] + 0.5 * y[t - 1] + 0.1 * rng.normal()
    te = transfer_entropy_discrete(x, y, n_bins=6)
    te_rev = transfer_entropy_discrete(y, x, n_bins=6)
    assert te > 0.01
    assert te > te_rev
