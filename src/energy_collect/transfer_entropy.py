"""
Rényi Transfer Entropy (RTE) via k-nearest-neighbour estimation.

Reference: Tabachová et al. (2026), arXiv:2601.01497 — Leonenko k-NN estimator
(Eq. 4–6) with optional effective RTE shuffle correction (Eq. 8).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from itertools import combinations
from typing import Any, Literal

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from scipy.special import digamma, gammaln

from energy_collect.config import AppConfig
from energy_collect.utils.zones import border_pairs

Method = Literal["knn", "discrete"]


def _unit_ball_volume(d: int) -> float:
    return float(np.pi ** (d / 2) / np.exp(gammaln(d / 2 + 1)))


def _ck_factor(k: int, alpha: float) -> float:
    """C_k from Tabachová et al. Eq. (6)."""
    if alpha == 1.0:
        return 1.0
    arg = k + 1 - alpha
    if arg <= 0:
        raise ValueError(f"Invalid k={k} for alpha={alpha}: need k + 1 - alpha > 0")
    return float(np.exp((gammaln(k) - gammaln(arg)) / (1 - alpha)))


def _standardize(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    if x.ndim == 1:
        x = x.reshape(-1, 1)
    mu = np.nanmean(x, axis=0)
    sigma = np.nanstd(x, axis=0)
    sigma[sigma < 1e-12] = 1.0
    return (x - mu) / sigma


def _knn_radius(x: np.ndarray, k: int) -> np.ndarray:
    """Euclidean distance to k-th nearest neighbour for each row (excluding self)."""
    x = _standardize(x)
    n = len(x)
    if n <= k:
        raise ValueError(f"Need more samples than k (n={n}, k={k})")
    tree = cKDTree(x)
    # k+1 neighbours: first is self at distance 0
    dists, _ = tree.query(x, k=k + 1, p=2, eps=0)
    if dists.ndim == 1:
        return np.maximum(dists[-1], 1e-12)
    radii = dists[:, k]
    return np.maximum(radii, 1e-12)


def renyi_entropy_knn(x: np.ndarray, *, k: int = 4, alpha: float = 1.0) -> float:
    """
    Leonenko k-NN Rényi entropy estimate for a sample X ∈ R^{N×d}.
    Returns entropy in bits (log base 2).
    """
    x = np.asarray(x, dtype=float)
    if x.ndim == 1:
        x = x.reshape(-1, 1)
    n, d = x.shape
    if n <= k + 1:
        return float("nan")

    rho = _knn_radius(x, k)

    if abs(alpha - 1.0) < 1e-9:
        # Kozachenko–Leonenko Shannon limit (α → 1), in bits
        vol = _unit_ball_volume(d)
        h_nats = digamma(n) - digamma(k) + np.log(vol) + (d / n) * np.sum(np.log(rho))
        return float(h_nats / np.log(2))

    bd = _unit_ball_volume(d)
    ck = _ck_factor(k, alpha)
    term = (n - 1) / (n * (bd ** (1 - alpha)) * (ck ** (1 - alpha)))
    summed = np.sum(rho ** (d * (1 - alpha))) / ((n - 1) ** alpha)
    val = term * summed
    if val <= 0:
        return float("nan")
    return float((1 / (1 - alpha)) * np.log2(val))


def _build_te_blocks(
    target: np.ndarray,
    source: np.ndarray,
    *,
    r: int,
    l: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Embedding blocks for apparent RTE (single source), Eq. (4) without Z:
      I1 = H(x_{t+1}, x^r_t), I2 = H(x^r_t), I3 = H(x_{t+1}, x^r_t, y^l_t), I4 = H(x^r_t, y^l_t)
    """
    target = np.asarray(target, dtype=float)
    source = np.asarray(source, dtype=float)
    n = len(target)
    start = max(r, l)
    if n <= start + 1:
        raise ValueError("Series too short for memory lengths")

    idx = np.arange(start, n)
    x_future = target[idx]
    x_past_cols = [target[idx - i] for i in range(1, r + 1)]
    y_past_cols = [source[idx - i] for i in range(1, l + 1)]

    i1 = np.column_stack([x_future] + x_past_cols)
    i2 = np.column_stack(x_past_cols)
    i3 = np.column_stack([x_future] + x_past_cols + y_past_cols)
    i4 = np.column_stack(x_past_cols + y_past_cols)
    return i1, i2, i3, i4


def renyi_transfer_entropy_knn(
    target: np.ndarray,
    source: np.ndarray,
    *,
    k: int = 4,
    alpha: float = 1.0,
    r: int = 1,
    l: int = 1,
) -> float:
    """
    Apparent Rényi transfer entropy Y → X (source → target), Eq. (2)/(4).
    """
    i1, i2, i3, i4 = _build_te_blocks(target, source, r=r, l=l)
    h1 = renyi_entropy_knn(i1, k=k, alpha=alpha)
    h2 = renyi_entropy_knn(i2, k=k, alpha=alpha)
    h3 = renyi_entropy_knn(i3, k=k, alpha=alpha)
    h4 = renyi_entropy_knn(i4, k=k, alpha=alpha)
    if any(np.isnan(v) for v in (h1, h2, h3, h4)):
        return float("nan")
    return float(h1 - h2 - h3 + h4)


def effective_renyi_transfer_entropy_knn(
    target: np.ndarray,
    source: np.ndarray,
    *,
    k: int = 4,
    alpha: float = 1.0,
    r: int = 1,
    l: int = 1,
    n_shuffles: int = 1,
    seed: int = 0,
) -> float:
    """
    Effective RTE (ERTE): RTE minus bias from shuffled source, Eq. (8).
    """
    rte = renyi_transfer_entropy_knn(target, source, k=k, alpha=alpha, r=r, l=l)
    if np.isnan(rte):
        return float("nan")

    rng = np.random.default_rng(seed)
    null_vals: list[float] = []
    for i in range(n_shuffles):
        shuffled = source.copy()
        rng.shuffle(shuffled)
        null = renyi_transfer_entropy_knn(
            target, shuffled, k=k, alpha=alpha, r=r, l=l, 
        )
        if not np.isnan(null):
            null_vals.append(null)

    if not null_vals:
        return rte
    bias = float(np.mean(null_vals))
    erte = rte - bias
    if abs(alpha - 1.0) < 1e-9:
        return max(0.0, erte)
    return erte


# --- Legacy discretized estimator (kept for tests / fallback) ---


def _entropy_from_counts(counts: np.ndarray) -> float:
    p = counts[counts > 0].astype(float)
    p = p / p.sum()
    return float(-np.sum(p * np.log2(p)))


def _joint_counts(*arrays: np.ndarray, n_bins: int) -> np.ndarray:
    if len(arrays) == 1:
        hist, _ = np.histogram(arrays[0], bins=n_bins, range=(0, n_bins))
        return hist.astype(float)
    combined = np.stack(arrays, axis=1)
    flat: dict[tuple[int, ...], int] = {}
    for row in combined:
        key = tuple(int(v) for v in row)
        flat[key] = flat.get(key, 0) + 1
    shape = (n_bins,) * len(arrays)
    out = np.zeros(shape, dtype=float)
    for key, c in flat.items():
        out[key] += c
    return out


def _digitize_series(x: np.ndarray, n_bins: int) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    finite = x[np.isfinite(x)]
    if len(finite) == 0:
        return np.zeros(len(x), dtype=int)
    qs = np.linspace(0, 100, n_bins + 1)
    edges = np.unique(np.percentile(finite, qs))
    if len(edges) < 3:
        edges = np.linspace(finite.min(), finite.max() + 1e-9, n_bins + 1)
    return np.clip(np.digitize(x, edges[1:-1], right=False), 0, n_bins - 1)


def transfer_entropy_discrete(
    target: np.ndarray,
    source: np.ndarray,
    *,
    lag: int = 1,
    n_bins: int = 8,
) -> float:
    """Discretized Schreiber TE (legacy)."""
    k = lag
    n = len(target)
    if n <= k + 1:
        return 0.0

    x_future = target[k:]
    x_past = target[:-k]
    y_past = source[:-k]
    if len(x_future) < 50:
        return 0.0

    xf = _digitize_series(x_future, n_bins)
    xp = _digitize_series(x_past, n_bins)
    yp = _digitize_series(y_past, n_bins)

    h_xf_xp = _entropy_from_counts(_joint_counts(xf, xp, n_bins=n_bins))
    h_xp = _entropy_from_counts(_joint_counts(xp, n_bins=n_bins))
    h_xf_xp_yp = _entropy_from_counts(_joint_counts(xf, xp, yp, n_bins=n_bins))
    h_xp_yp = _entropy_from_counts(_joint_counts(xp, yp, n_bins=n_bins))
    return max(0.0, (h_xf_xp - h_xp) - (h_xf_xp_yp - h_xp_yp))


def _estimate_te(
    target: np.ndarray,
    source: np.ndarray,
    *,
    method: Method,
    k: int,
    alpha: float,
    r: int,
    l: int,
    effective: bool,
    n_bins: int,
    seed: int,
) -> float:
    if method == "discrete":
        return transfer_entropy_discrete(target, source, lag=1, n_bins=n_bins)
    if effective:
        return effective_renyi_transfer_entropy_knn(
            target, source, k=k, alpha=alpha, r=r, l=l, seed=seed
        )
    val = renyi_transfer_entropy_knn(target, source, k=k, alpha=alpha, r=r, l=l)
    if np.isnan(val):
        return float("nan")
    if abs(alpha - 1.0) < 1e-9:
        return max(0.0, val)
    return val


def _align_pair(wide: pd.DataFrame, a: str, b: str) -> tuple[np.ndarray, np.ndarray]:
    sub = wide[[a, b]].dropna()
    return sub[a].to_numpy(), sub[b].to_numpy()


def pair_te_both(
    xa: np.ndarray,
    xb: np.ndarray,
    *,
    method: Method = "discrete",
    k: int = 4,
    alpha: float = 1.0,
    r: int = 1,
    l: int = 1,
    effective: bool = False,
    n_bins: int = 8,
    seed: int = 0,
    min_len: int = 80,
) -> tuple[float, float]:
    """
    TE in both directions for aligned series xa, xb.

    Returns (TE_{xb → xa}, TE_{xa → xb}) i.e. (b→a, a→b), matching compute_te_edges
    where te_ab is estimated with target=xa, source=xb so the edge is from b to a.
    """
    if len(xa) < min_len or len(xb) < min_len:
        return float("nan"), float("nan")
    te_b_to_a = _estimate_te(
        xa, xb, method=method, k=k, alpha=alpha, r=r, l=l,
        effective=effective, n_bins=n_bins, seed=seed,
    )
    te_a_to_b = _estimate_te(
        xb, xa, method=method, k=k, alpha=alpha, r=r, l=l,
        effective=effective, n_bins=n_bins, seed=seed + 1,
    )
    return float(te_b_to_a), float(te_a_to_b)


def compute_te_edges(
    prices: pd.DataFrame,
    *,
    min_te: float = 0.005,
    method: Method = "knn",
    k: int = 4,
    alpha: float = 1.0,
    r: int = 1,
    l: int = 1,
    effective: bool = True,
    n_bins: int = 8,
    max_pairs: int | None = None,
    neighbor_only: bool = False,
    zones_config: list[dict] | None = None,
    seed: int = 42,
    min_len: int | None = None,
    include_below_threshold: bool = False,
) -> list[dict[str, Any]]:
    wide = prices.pivot_table(index="timestamp", columns="zone", values="value", aggfunc="mean")
    zones = sorted(wide.columns.tolist())

    pair_list: list[tuple[str, str]] = []
    if neighbor_only and zones_config:
        for p in border_pairs(zones_config):
            if p.from_zone in zones and p.to_zone in zones:
                pair_list.append((p.from_zone, p.to_zone))
    else:
        pair_list = [(a, b) for a, b in combinations(zones, 2)]

    if max_pairs:
        pair_list = pair_list[:max_pairs]

    if min_len is None:
        min_len = 720 if method == "discrete" else max(500, (max(r, l) + 1) * 24 * 14)
    edges: list[dict[str, Any]] = []
    pair_seed = seed
    te_type = "renyi_transfer_entropy" if method == "knn" else "transfer_entropy"

    for a, b in pair_list:
        xa, xb = _align_pair(wide, a, b)
        te_b_to_a, te_a_to_b = pair_te_both(
            xa, xb, method=method, k=k, alpha=alpha, r=r, l=l,
            effective=effective, n_bins=n_bins, seed=pair_seed, min_len=min_len,
        )
        pair_seed += 2

        for src, tgt, te in ((b, a, te_b_to_a), (a, b, te_a_to_b)):
            if np.isnan(te):
                continue
            if not include_below_threshold and te < min_te:
                continue
            edges.append({
                "from": src,
                "to": tgt,
                "te": round(te, 5),
                "type": te_type,
                "alpha": alpha,
            })

    edges.sort(key=lambda e: -e["te"])
    return edges


def write_te_graph_manifest(
    config: AppConfig,
    year: int,
    edges: list[dict[str, Any]],
    *,
    meta: dict[str, Any],
) -> Path:
    """Write dependency_graph_{year}_te.json with directed RTE edges."""
    base = config.data_root / "manifests" / f"dependency_graph_{year}.json"
    nodes = []
    if base.exists():
        graph = json.loads(base.read_text(encoding="utf-8"))
        nodes = graph.get("nodes", [])

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "year": year,
        "nodes": nodes,
        "edges": {"renyi_transfer_entropy": edges},
        "stats": {
            "nodes": len(nodes),
            "rte_edges": len(edges),
            **{k: v for k, v in meta.items() if k not in ("edges", "top_edges")},
        },
        "method": meta.get("method"),
    }
    path = config.data_root / "manifests" / f"dependency_graph_{year}_te.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return path


def run_transfer_entropy(
    config: AppConfig,
    year: int,
    *,
    use_deseasonalised: bool = True,
    min_te: float = 0.005,
    neighbor_only: bool = False,
    method: Method = "knn",
    k: int = 4,
    alpha: float = 1.0,
    r: int = 1,
    l: int = 1,
    effective: bool = True,
    n_bins: int = 8,
) -> dict[str, Any]:
    if use_deseasonalised:
        path = config.data_root / "processed" / "entsoe" / f"prices_deseasonalised_{year}.parquet"
        if not path.exists():
            from energy_collect.seasonality import run_seasonality_decomposition

            run_seasonality_decomposition(config, year, dataset="prices")
        prices = pd.read_parquet(path)
    else:
        path = config.data_root / "processed" / "entsoe" / f"prices_{year}.parquet"
        prices = pd.read_parquet(path)

    prices["timestamp"] = pd.to_datetime(prices["timestamp"], utc=True)
    edges = compute_te_edges(
        prices,
        min_te=min_te,
        method=method,
        k=k,
        alpha=alpha,
        r=r,
        l=l,
        effective=effective,
        n_bins=n_bins,
        neighbor_only=neighbor_only,
        zones_config=config.zones if neighbor_only else None,
    )

    border_edges_all = compute_te_edges(
        prices,
        min_te=0.0,
        method=method,
        k=k,
        alpha=alpha,
        r=r,
        l=l,
        effective=effective,
        n_bins=n_bins,
        neighbor_only=True,
        zones_config=config.zones,
    )
    for e in border_edges_all:
        e["passes_threshold"] = e["te"] >= min_te

    if method == "knn":
        method_desc = (
            f"k-NN Rényi TE (Leonenko), α={alpha}, k={k}, r={r}, l={l}"
            + (", effective (shuffle-corrected)" if effective else "")
        )
    else:
        method_desc = f"discretized Schreiber TE (k=1, {n_bins} bins)"

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "year": year,
        "method": method_desc,
        "estimator": method,
        "alpha": alpha,
        "k_neighbors": k,
        "memory_r": r,
        "memory_l": l,
        "effective_rte": effective,
        "reference": "Tabachová et al. (2026) arXiv:2601.01497",
        "min_te": min_te,
        "use_deseasonalised": use_deseasonalised,
        "neighbor_only": neighbor_only,
        "edge_count": len(edges),
        "edges": edges,
        "top_edges": edges[:20],
        "border_edge_count": len(border_edges_all),
        "border_edges_all": border_edges_all,
    }

    out_dir = config.data_root / "manifests" / "dashboard"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"transfer_entropy_{year}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["output_path"] = str(out)

    graph_path = write_te_graph_manifest(config, year, edges, meta=report)
    report["graph_path"] = str(graph_path)
    return report
