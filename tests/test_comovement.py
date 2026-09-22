"""Tests for the RQ1-RQ3 co-movement analysis."""

from __future__ import annotations

import numpy as np
import pandas as pd

from energy_collect.comovement import (
    _merged_clusters,
    _same_group,
    _split_clusters,
    adjusted_rand_index,
    cluster_count_scan,
    cluster_mode_matrix,
    eigen_spectrum,
    hop_distances,
    partition,
    select_k,
    silhouette,
    topology,
)


def _block_panel(n_hours: int = 3000, seed: int = 0) -> pd.DataFrame:
    """Panel with one market factor plus three bloc factors and noise."""
    rng = np.random.default_rng(seed)
    market = rng.normal(size=n_hours)
    blocs = {"A": ["a1", "a2", "a3"], "B": ["b1", "b2", "b3"], "C": ["c1", "c2", "c3"]}
    data = {}
    for name, members in blocs.items():
        local = rng.normal(size=n_hours)
        for zone in members:
            data[zone] = market + 1.2 * local + 0.6 * rng.normal(size=n_hours)
    index = pd.date_range("2025-01-01", periods=n_hours, freq="h", tz="UTC")
    return pd.DataFrame(data, index=index)


# --- RQ1 -------------------------------------------------------------------


def test_eigen_spectrum_recovers_market_and_bloc_modes():
    spec = eigen_spectrum(_block_panel(), n_surrogates=60, seed=1)
    # One market mode plus two independent bloc directions (three blocs span
    # two dimensions once the common mode is removed).
    assert spec["k_significant_95"] == 3
    assert spec["cluster_dimensions"] == 2
    assert 0.3 < spec["variance_market_mode"] < 0.7
    assert spec["eigenvalues"][0] > spec["eigenvalues"][1]
    shares = spec["variance_market_mode"] + spec["variance_cluster_modes"] + spec["variance_noise_bulk"]
    assert abs(shares - 1.0) < 1e-6


def test_eigen_spectrum_finds_no_structure_in_independent_noise():
    rng = np.random.default_rng(5)
    index = pd.date_range("2025-01-01", periods=2000, freq="h", tz="UTC")
    panel = pd.DataFrame(rng.normal(size=(2000, 8)), index=index, columns=list("abcdefgh"))
    spec = eigen_spectrum(panel, n_surrogates=60, seed=2)
    assert spec["k_significant_95"] == 0


def test_surrogate_null_is_stricter_than_naive_bound_under_autocorrelation():
    """Red-noise columns must not be read as shared structure."""
    rng = np.random.default_rng(11)
    n = 4000
    cols = {}
    for name in "abcdefgh":
        x = np.zeros(n)
        for t in range(1, n):
            x[t] = 0.9 * x[t - 1] + rng.normal()
        cols[name] = x
    panel = pd.DataFrame(cols, index=pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC"))
    spec = eigen_spectrum(panel, n_surrogates=80, seed=3)
    assert spec["mp_upper_effective"] > spec["mp_upper_naive"]
    assert spec["n_effective"] < spec["n_hours"]
    assert spec["k_significant_95"] <= 1


# --- RQ2 -------------------------------------------------------------------


def test_adjusted_rand_index_bounds():
    a = [1, 1, 2, 2, 3, 3]
    assert adjusted_rand_index(a, a) == 1.0
    assert adjusted_rand_index(a, [2, 2, 3, 3, 1, 1]) == 1.0
    assert adjusted_rand_index(a, [1, 2, 1, 2, 1, 2]) < 0.2


def test_partition_recovers_blocs_and_ignores_market_mode():
    panel = _block_panel()
    corr = np.corrcoef(panel.to_numpy().T)
    labels = partition(corr, 3, 3)
    groups = {frozenset(np.asarray(panel.columns)[labels == c]) for c in set(labels.tolist())}
    assert groups == {
        frozenset({"a1", "a2", "a3"}),
        frozenset({"b1", "b2", "b3"}),
        frozenset({"c1", "c2", "c3"}),
    }
    assert silhouette(corr, labels, 3) > 0.3


def test_cluster_mode_matrix_drops_the_market_mode():
    panel = _block_panel()
    corr = np.corrcoef(panel.to_numpy().T)
    group = cluster_mode_matrix(corr, 3)
    off = ~np.eye(len(corr), dtype=bool)
    # Removing the all-positive market mode must push the average off-diagonal
    # correlation down towards zero.
    assert group[off].mean() < corr[off].mean()
    assert np.allclose(np.diag(group), 1.0)


def test_select_k_rejects_singleton_partitions():
    scan = [
        {"k": 2, "silhouette": 0.30, "sizes": [6, 3]},
        {"k": 3, "silhouette": 0.55, "sizes": [3, 3, 3]},
        {"k": 4, "silhouette": 0.56, "sizes": [3, 3, 2, 1]},
    ]
    assert select_k(scan) == 3
    assert select_k(scan, k_cap=2) == 2


def test_cluster_count_scan_reports_sizes():
    rows = cluster_count_scan(_block_panel(), n_modes=3, k_max=4)
    assert [r["k"] for r in rows] == [2, 3, 4]
    assert all(sum(r["sizes"]) == 9 for r in rows)


def test_merge_and_split_diagnostics():
    base = np.array([1, 1, 2, 2, 3, 3])
    merged = np.array([1, 1, 1, 1, 2, 2])
    assert _merged_clusters(base, merged) == [[1, 2]]
    assert _split_clusters(base, merged) == []
    split = np.array([1, 2, 3, 3, 4, 4])
    assert _split_clusters(base, split) == [1]
    assert _same_group(base, merged, 0) is True
    assert _same_group(base, split, 0) is False


# --- RQ3 -------------------------------------------------------------------


def test_topology_and_hop_distances():
    zones_config = [
        {"code": "A", "neighbors": ["B"]},
        {"code": "B", "neighbors": ["C"]},
        {"code": "C", "neighbors": []},
        {"code": "D", "neighbors": ["ZZ"]},
    ]
    adjacency = topology(zones_config, ["A", "B", "C", "D"])
    assert adjacency["B"] == {"A", "C"}
    # Neighbours outside the panel are dropped rather than invented.
    assert adjacency["D"] == set()
    hops = hop_distances(adjacency)
    assert hops["A"]["C"] == 2
    assert "D" not in hops["A"]
