"""Tests for meeting-point analyses (mismatch, TE reversals, nested averages)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from energy_collect.meeting_analyses import (
    classify_mismatch,
    compute_nested_te,
    detect_reversals,
)
from energy_collect.transfer_entropy import pair_te_both, transfer_entropy_discrete


def test_classify_mismatch_fr_es_type():
    assert (
        classify_mismatch(
            mean_abs_mw=2000,
            pearson_r=0.2,
            te_max=0.01,
            flow_high=500,
            r_high=0.7,
            te_high=0.02,
        )
        == "congested_trade"
    )
    assert (
        classify_mismatch(
            mean_abs_mw=50,
            pearson_r=0.95,
            te_max=0.05,
            flow_high=500,
            r_high=0.7,
            te_high=0.02,
        )
        == "paper_coupling"
    )
    assert (
        classify_mismatch(
            mean_abs_mw=2000,
            pearson_r=0.9,
            te_max=0.05,
            flow_high=500,
            r_high=0.7,
            te_high=0.02,
        )
        == "aligned_strong"
    )


def test_detect_reversals_hod():
    pair_results = {
        "FR|ES": {
            "bins": {
                "00": {"net_a_minus_b": 0.04, "leader": "FR"},
                "08": {"net_a_minus_b": 0.05, "leader": "FR"},
                "12": {"net_a_minus_b": -0.05, "leader": "ES"},
                "18": {"net_a_minus_b": -0.04, "leader": "ES"},
            }
        }
    }
    revs = detect_reversals(pair_results, min_abs_net=0.03)
    assert len(revs) == 1
    assert revs[0]["a"] == "FR"
    assert "00" in revs[0]["a_leads_in"]
    assert "12" in revs[0]["b_leads_in"]


def test_pair_te_both_direction():
    rng = np.random.default_rng(0)
    n = 400
    y = rng.normal(size=n)
    x = np.zeros(n)
    for t in range(1, n):
        x[t] = 0.5 * y[t - 1] + 0.1 * rng.normal()
    b_to_a, a_to_b = pair_te_both(x, y, method="discrete", min_len=80, n_bins=6)
    # y → x should dominate (source y, target x) => b_to_a with xa=x xb=y
    assert b_to_a > a_to_b


def test_nested_te_synthetic_short():
    idx = pd.date_range("2025-01-01", periods=24 * 40, freq="h", tz="UTC")
    rng = np.random.default_rng(1)
    a = rng.normal(size=len(idx))
    b = np.roll(a, 1) + 0.2 * rng.normal(size=len(idx))
    wide = pd.DataFrame({"FR": a, "ES": b}, index=idx)
    out = compute_nested_te(
        wide,
        ["FR", "ES"],
        n_bins=4,
        min_len_year=80,
        min_len_month=40,
        min_len_week=40,
        min_len_hod=20,
    )
    assert out["pair_count"] == 1
    assert len(out["scale_table"]) == 1
    row = out["scale_table"][0]
    assert "year_a_to_b" in row
    assert len(row["hod_net_series"]) == 24 or len(row["hod_net_series"]) > 0


def test_discrete_te_positive():
    rng = np.random.default_rng(2)
    n = 800
    y = rng.normal(size=n)
    x = np.zeros(n)
    for t in range(1, n):
        x[t] = 0.6 * y[t - 1] + 0.2 * rng.normal()
    assert transfer_entropy_discrete(x, y, n_bins=6) > 0
