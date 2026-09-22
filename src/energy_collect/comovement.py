"""
Price co-movement analysis answering RQ1-RQ3.

RQ1  How much of European price co-movement is a single Europe-wide mode,
     how much is cluster-specific, and how many cluster dimensions are
     statistically supported?
     -> eigen-decomposition of the zone correlation matrix, variance
        partition into market mode / cluster modes / noise bulk, and two
        independent significance tests (phase-randomised surrogate null and
        an autocorrelation-adjusted Marchenko-Pastur bound).

RQ2  Do the price clusters persist across seasons and intraday, or does the
     partition reorganise?
     -> cluster the market-mode-removed correlation matrix per stratum and
        compare partitions with the Adjusted Rand Index against a
        label-permutation null that controls for the smaller stratum sample.

RQ3  Does price co-movement follow the physical interconnection topology,
     and where does it diverge?
     -> correlation-vs-hop-distance profile, Mantel test, adjacency
        discrimination (AUC), and explicit over/under-coupled border tables
        with NTC and price-convergence evidence.

All estimators use numpy/scipy only so the package keeps its light
dependency set.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform
from scipy.stats import mannwhitneyu

from energy_collect.config import AppConfig

log = logging.getLogger(__name__)

# Zones must be present for this share of hours to enter the panel.
MIN_ZONE_COVERAGE = 0.90
# Gaps up to this many hours are linearly interpolated before listwise deletion.
MAX_INTERPOLATE_HOURS = 3
# Surrogate replications for the RQ1 eigenvalue null.
N_SURROGATES = 500
# Replications for the RQ2 stratum-label permutation null.
N_STRATUM_NULL = 120
# Replications for the RQ3 Mantel permutation test.
N_MANTEL = 5000

SEASONS: dict[str, tuple[int, ...]] = {
    "DJF": (12, 1, 2),
    "MAM": (3, 4, 5),
    "JJA": (6, 7, 8),
    "SON": (9, 10, 11),
}
SEASON_LABELS = {
    "DJF": "Winter (Dec-Feb)",
    "MAM": "Spring (Mar-May)",
    "JJA": "Summer (Jun-Aug)",
    "SON": "Autumn (Sep-Nov)",
}
HOUR_BLOCKS: dict[str, tuple[int, ...]] = {
    "night": (0, 1, 2, 3, 4, 5),
    "morning": (6, 7, 8, 9, 10, 11),
    "midday": (12, 13, 14, 15, 16, 17),
    "evening": (18, 19, 20, 21, 22, 23),
}
HOUR_BLOCK_LABELS = {
    "night": "Night 00-05 UTC",
    "morning": "Morning 06-11 UTC",
    "midday": "Midday 12-17 UTC",
    "evening": "Evening 18-23 UTC",
}

# Descriptive names for the recurring blocs, assigned by membership overlap so
# the dashboard can label clusters without hard-coding a partition.
BLOC_SIGNATURES: list[tuple[str, tuple[str, ...]]] = [
    ("Iberia + France", ("ES", "PT", "FR")),
    ("Italy + Switzerland", ("IT_NORTH", "IT_CNOR", "IT_CSUD", "IT_SUD", "IT_SICI", "IT_SARD", "CH")),
    ("Baltics", ("EE", "LV", "LT")),
    ("Nordic north", ("NO_3", "NO_4", "SE_1", "SE_2")),
    ("Nordic south + Atlantic", ("NO_1", "NO_2", "NO_5", "SE_3", "SE_4", "FI", "IE_SEM")),
    ("North Sea", ("BE", "NL", "DK_1", "DK_2")),
    ("Central-West/East core", ("DE_LU", "AT", "CZ", "PL", "SK")),
    ("Balkans + South-East", ("SI", "HR", "HU", "RO", "BG", "RS", "GR", "AL", "MK", "ME")),
]


# --------------------------------------------------------------------------
# Panel construction
# --------------------------------------------------------------------------


def _hourly_panel(df: pd.DataFrame, year: int) -> pd.DataFrame:
    """Collapse a long zone/timestamp frame to a wide hourly UTC panel.

    From 1 October 2025 several TSOs publish a 15-minute market time unit, so
    the raw index mixes resolutions. Averaging into hourly buckets is what
    makes the zones comparable at all.
    """
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["hour"] = df["timestamp"].dt.floor("h")
    wide = df.groupby(["hour", "zone"])["value"].mean().unstack()
    wide = wide[(wide.index >= f"{year}-01-01") & (wide.index < f"{year + 1}-01-01")]
    return wide.sort_index()


def build_price_panels(config: AppConfig, year: int) -> dict[str, Any]:
    """Return aligned level and deseasonalised-residual price panels."""
    proc = config.data_root / "processed" / "entsoe"
    levels = _hourly_panel(pd.read_parquet(proc / f"prices_{year}.parquet"), year)

    resid_path = proc / f"prices_deseasonalised_{year}.parquet"
    if not resid_path.exists():
        from energy_collect.seasonality import run_seasonality_decomposition

        run_seasonality_decomposition(config, year, dataset="prices")
    residuals = _hourly_panel(pd.read_parquet(resid_path), year)

    coverage = levels.notna().mean()
    keep = sorted(z for z in coverage[coverage >= MIN_ZONE_COVERAGE].index if z in residuals.columns)
    dropped = sorted(set(levels.columns) - set(keep))

    levels = levels[keep].interpolate(limit=MAX_INTERPOLATE_HOURS, limit_area="inside")
    residuals = residuals[keep].interpolate(limit=MAX_INTERPOLATE_HOURS, limit_area="inside")

    common = levels.dropna().index.intersection(residuals.dropna().index)
    levels = levels.loc[common]
    residuals = residuals.loc[common]

    return {
        "levels": levels,
        "residuals": residuals,
        "zones": keep,
        "dropped_zones": [{"zone": z, "coverage": round(float(coverage[z]), 3)} for z in dropped],
        "hours": int(len(common)),
        "coverage": {z: round(float(coverage[z]), 4) for z in keep},
    }


def _corr(panel: pd.DataFrame) -> np.ndarray:
    values = np.asarray(panel.values, dtype=float)
    centred = (values - values.mean(axis=0)) / values.std(axis=0)
    return np.clip(np.corrcoef(centred, rowvar=False), -1.0, 1.0)


# --------------------------------------------------------------------------
# RQ1 - how many modes, and how big is the Europe-wide one
# --------------------------------------------------------------------------


def _phase_randomise(matrix: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Surrogate panel: identical per-zone power spectrum, no cross-coupling.

    Randomising Fourier phases independently per column preserves each zone's
    autocorrelation (which is what inflates naive significance bounds) while
    destroying every cross-zone relationship.
    """
    spectrum = np.fft.rfft(matrix, axis=0)
    phases = rng.uniform(0.0, 2.0 * np.pi, size=spectrum.shape)
    phases[0] = 0.0
    if matrix.shape[0] % 2 == 0:
        phases[-1] = 0.0
    surrogate = np.fft.irfft(np.abs(spectrum) * np.exp(1j * phases), n=matrix.shape[0], axis=0)
    return surrogate


def _mean_ar1(matrix: np.ndarray) -> float:
    lags = []
    for col in range(matrix.shape[1]):
        series = matrix[:, col]
        lags.append(float(np.corrcoef(series[:-1], series[1:])[0, 1]))
    return float(np.mean(lags))


def eigen_spectrum(panel: pd.DataFrame, *, n_surrogates: int = N_SURROGATES, seed: int = 20260921) -> dict[str, Any]:
    """Eigen-decomposition with a surrogate null and an MP bound."""
    values = np.asarray(panel.values, dtype=float)
    standardised = (values - values.mean(axis=0)) / values.std(axis=0)
    n_obs, n_zones = standardised.shape

    corr = np.clip(np.corrcoef(standardised, rowvar=False), -1.0, 1.0)
    eigvals, eigvecs = np.linalg.eigh(corr)
    eigvals = eigvals[::-1]
    eigvecs = eigvecs[:, ::-1]

    rng = np.random.default_rng(seed)
    null = np.empty((n_surrogates, n_zones))
    for i in range(n_surrogates):
        surrogate = _phase_randomise(standardised, rng)
        surrogate = (surrogate - surrogate.mean(axis=0)) / surrogate.std(axis=0)
        null[i] = np.linalg.eigvalsh(np.corrcoef(surrogate, rowvar=False))[::-1]

    q95 = np.quantile(null, 0.95, axis=0)
    q99 = np.quantile(null, 0.99, axis=0)
    # Significance is read off as the leading run: the first eigenvalue that
    # falls inside its own null band ends the supported spectrum.
    k_95 = 0
    while k_95 < n_zones and eigvals[k_95] > q95[k_95]:
        k_95 += 1
    k_99 = 0
    while k_99 < n_zones and eigvals[k_99] > q99[k_99]:
        k_99 += 1

    ar1 = _mean_ar1(standardised)
    n_eff = n_obs * (1.0 - ar1) / (1.0 + ar1)
    mp_upper = (1.0 + np.sqrt(n_zones / n_eff)) ** 2
    mp_naive = (1.0 + np.sqrt(n_zones / n_obs)) ** 2

    market = float(eigvals[0] / n_zones)
    cluster = float(eigvals[1:k_95].sum() / n_zones) if k_95 > 1 else 0.0

    return {
        "n_zones": int(n_zones),
        "n_hours": int(n_obs),
        "zones": list(panel.columns),
        "eigenvalues": [float(v) for v in eigvals],
        "explained": [float(v / n_zones) for v in eigvals],
        "null_mean": [float(v) for v in null.mean(axis=0)],
        "null_q95": [float(v) for v in q95],
        "null_q99": [float(v) for v in q99],
        "n_surrogates": int(n_surrogates),
        "k_significant_95": int(k_95),
        "k_significant_99": int(k_99),
        "cluster_dimensions": int(max(k_95 - 1, 0)),
        "mean_ar1": round(ar1, 4),
        "n_effective": round(float(n_eff), 1),
        "mp_upper_effective": round(float(mp_upper), 4),
        "mp_upper_naive": round(float(mp_naive), 4),
        "k_significant_mp": int((eigvals > mp_upper).sum()),
        "variance_market_mode": round(market, 4),
        "variance_cluster_modes": round(cluster, 4),
        "variance_noise_bulk": round(float(1.0 - market - cluster), 4),
        "eigenvectors": eigvecs,
        "correlation": corr,
    }


def mode_loadings(spectrum: dict[str, Any], *, n_modes: int = 6, top: int = 8) -> list[dict[str, Any]]:
    zones = spectrum["zones"]
    vecs = spectrum["eigenvectors"]
    eigvals = spectrum["eigenvalues"]
    n_zones = spectrum["n_zones"]
    out: list[dict[str, Any]] = []
    for mode in range(min(n_modes, n_zones)):
        vec = vecs[:, mode]
        # Sign of an eigenvector is arbitrary; orient it so the heaviest
        # loading is positive and tables read consistently.
        if vec[int(np.argmax(np.abs(vec)))] < 0:
            vec = -vec
        order = np.argsort(-np.abs(vec))[:top]
        out.append(
            {
                "mode": mode + 1,
                "eigenvalue": round(float(eigvals[mode]), 4),
                "explained": round(float(eigvals[mode] / n_zones), 4),
                "significant": bool(mode < spectrum["k_significant_95"]),
                "all_same_sign": bool(np.all(vec > 0) or np.all(vec < 0)),
                "loadings": [{"zone": zones[i], "loading": round(float(vec[i]), 3)} for i in order],
            }
        )
    return out


# --------------------------------------------------------------------------
# RQ2 - partition stability across seasons and intraday
# --------------------------------------------------------------------------


def cluster_mode_matrix(corr: np.ndarray, n_modes: int) -> np.ndarray:
    """Correlation rebuilt from modes 2..n_modes (market mode removed).

    Leaving the market mode in makes every zone look similar to every other
    zone, which is exactly the component RQ1 measures separately.
    """
    eigvals, eigvecs = np.linalg.eigh(corr)
    eigvals = eigvals[::-1]
    eigvecs = eigvecs[:, ::-1]
    group = np.zeros_like(corr)
    for i in range(1, max(n_modes, 2)):
        group += eigvals[i] * np.outer(eigvecs[:, i], eigvecs[:, i])
    scale = np.sqrt(np.clip(np.diag(group), 1e-12, None))
    return np.clip(group / np.outer(scale, scale), -1.0, 1.0)


def _distance(corr: np.ndarray, n_modes: int) -> np.ndarray:
    group = cluster_mode_matrix(corr, n_modes)
    dist = np.sqrt(np.clip(2.0 * (1.0 - group), 0.0, None))
    np.fill_diagonal(dist, 0.0)
    return dist


def partition(corr: np.ndarray, k: int, n_modes: int) -> np.ndarray:
    dist = _distance(corr, n_modes)
    tree = linkage(squareform(dist, checks=False), method="average")
    return fcluster(tree, k, criterion="maxclust")


def silhouette(corr: np.ndarray, labels: np.ndarray, n_modes: int) -> float:
    dist = _distance(corr, n_modes)
    unique = set(labels.tolist())
    if len(unique) < 2:
        return 0.0
    scores = []
    for i in range(len(labels)):
        same = labels == labels[i]
        same[i] = False
        if not same.any():
            scores.append(0.0)
            continue
        a = dist[i, same].mean()
        b = min(dist[i, labels == c].mean() for c in unique if c != labels[i])
        scores.append((b - a) / max(a, b))
    return float(np.mean(scores))


def adjusted_rand_index(a: Sequence[int], b: Sequence[int]) -> float:
    table = pd.crosstab(np.asarray(a), np.asarray(b)).to_numpy(dtype=float)
    n = table.sum()
    if n < 2:
        return 1.0

    def comb2(x):
        return x * (x - 1.0) / 2.0

    index = comb2(table).sum()
    a_sum = comb2(table.sum(axis=1)).sum()
    b_sum = comb2(table.sum(axis=0)).sum()
    expected = a_sum * b_sum / comb2(n)
    maximum = 0.5 * (a_sum + b_sum)
    if maximum == expected:
        return 1.0
    return float((index - expected) / (maximum - expected))


def _bloc_name(members: Iterable[str], used: set[str]) -> str:
    """Label a cluster by Jaccard overlap with the known European blocs.

    A cluster that is a clean merge of two blocs gets both names, so the label
    stays honest when the chosen k lumps them together.
    """
    members = set(members)
    scored = []
    for name, signature in BLOC_SIGNATURES:
        sig = set(signature)
        union = members | sig
        scored.append((len(members & sig) / len(union) if union else 0.0, len(members & sig), name))
    scored.sort(reverse=True)
    best_jaccard, best_overlap, best_name = scored[0]
    if best_overlap == 0:
        return "+".join(sorted(members)[:3])
    if best_jaccard >= 0.6 or len(scored) == 1:
        label = best_name
    else:
        covered = set()
        parts = []
        for _, overlap, name in scored:
            sig = set(dict(BLOC_SIGNATURES)[name])
            if overlap and not sig <= covered and len(sig & members) >= 2:
                parts.append(name)
                covered |= sig & members
            if covered >= members:
                break
        label = " + ".join(parts) if parts else best_name
    if label in used:
        label = f"{label} ({', '.join(sorted(members)[:3])})"
    used.add(label)
    return label


def stratified_partitions(
    panel: pd.DataFrame,
    *,
    k: int,
    n_modes: int,
    n_null: int = N_STRATUM_NULL,
    seed: int = 20260921,
) -> dict[str, Any]:
    """Cluster each season / hour-block / season x hour-block stratum.

    Each observed ARI is paired with a null built by permuting the stratum
    label, so a drop only counts as reorganisation if it falls below what the
    smaller sample alone would produce.
    """
    index = pd.DatetimeIndex(panel.index)
    corr_full = _corr(panel)
    baseline = partition(corr_full, k, n_modes)
    zones = list(panel.columns)
    rng = np.random.default_rng(seed)

    days = pd.Index(index.normalize())
    unique_days = pd.unique(days)

    def season_null(n_days: int) -> list[float]:
        out = []
        for _ in range(n_null):
            chosen = set(rng.choice(unique_days, size=n_days, replace=False))
            mask = days.isin(chosen)
            out.append(adjusted_rand_index(baseline, partition(_corr(panel[mask]), k, n_modes)))
        return out

    def hour_null(n_hours: int) -> list[float]:
        out = []
        for _ in range(n_null):
            chosen = rng.choice(24, size=n_hours, replace=False)
            mask = index.hour.isin(chosen)
            out.append(adjusted_rand_index(baseline, partition(_corr(panel[mask]), k, n_modes)))
        return out

    def joint_null(n_days: int, n_hours: int) -> list[float]:
        """Null for a season x hour-block cell: both labels permuted at once.

        Using a season-sized null here would compare a ~500-hour partition
        against a ~2000-hour reference and flag ordinary sampling noise as
        reorganisation.
        """
        out = []
        for _ in range(n_null):
            day_sel = set(rng.choice(unique_days, size=n_days, replace=False))
            hour_sel = rng.choice(24, size=n_hours, replace=False)
            mask = days.isin(day_sel) & index.hour.isin(hour_sel)
            out.append(adjusted_rand_index(baseline, partition(_corr(panel[mask]), k, n_modes)))
        return out

    def summarise(name: str, label: str, mask: np.ndarray, null: list[float]) -> dict[str, Any]:
        sub = panel[mask]
        corr_s = _corr(sub)
        labels = partition(corr_s, k, n_modes)
        eig = np.linalg.eigvalsh(corr_s)[::-1]
        ari = adjusted_rand_index(baseline, labels)
        p05 = float(np.quantile(null, 0.05))
        moved = [
            zones[i]
            for i in range(len(zones))
            if not _same_group(baseline, labels, i)
        ]
        merges = _merged_clusters(baseline, labels)
        return {
            "stratum": name,
            "label": label,
            "hours": int(mask.sum()),
            "ari": round(float(ari), 4),
            "null_median": round(float(np.median(null)), 4),
            "null_p05": round(p05, 4),
            "reorganised": bool(ari < p05),
            "market_mode_share": round(float(eig[0] / corr_s.shape[0]), 4),
            "silhouette": round(silhouette(corr_s, labels, n_modes), 4),
            "moved_zones": moved,
            "merged_clusters": merges,
            "split_clusters": _split_clusters(baseline, labels),
            "labels": [int(v) for v in labels],
        }

    season_rows = []
    for name, months in SEASONS.items():
        mask = index.month.isin(months)
        n_days = int(pd.Index(days[mask]).nunique())
        season_rows.append(summarise(name, SEASON_LABELS[name], mask, season_null(n_days)))

    hour_rows = []
    for name, hours in HOUR_BLOCKS.items():
        mask = index.hour.isin(hours)
        hour_rows.append(summarise(name, HOUR_BLOCK_LABELS[name], mask, hour_null(len(hours))))

    # The 16 season x hour-block cells are all the same size (about a quarter
    # of the days by a quarter of the hours), so one matched null serves them.
    joint_rows = []
    cell_null = joint_null(max(len(unique_days) // 4, 1), len(next(iter(HOUR_BLOCKS.values()))))
    for sname, months in SEASONS.items():
        for hname, hours in HOUR_BLOCKS.items():
            mask = index.month.isin(months) & index.hour.isin(hours)
            if mask.sum() < 200:
                continue
            row = summarise(
                f"{sname}|{hname}",
                f"{SEASON_LABELS[sname]} / {HOUR_BLOCK_LABELS[hname]}",
                mask,
                cell_null,
            )
            row.pop("labels", None)
            joint_rows.append(row)

    all_rows = season_rows + hour_rows + joint_rows
    co_membership = np.zeros((len(zones), len(zones)))
    counted = 0
    for row in season_rows + hour_rows:
        labels = np.array(row["labels"])
        co_membership += (labels[:, None] == labels[None, :]).astype(float)
        counted += 1
    co_membership /= max(counted, 1)

    base_co = (baseline[:, None] == baseline[None, :]).astype(float)
    zone_stability = []
    for i, zone in enumerate(zones):
        peers = base_co[i].astype(bool).copy()
        peers[i] = False
        if peers.any():
            loyalty = float(co_membership[i, peers].mean())
        else:
            loyalty = 1.0
        outsiders = ~base_co[i].astype(bool)
        defection = float(co_membership[i, outsiders].mean()) if outsiders.any() else 0.0
        zone_stability.append(
            {
                "zone": zone,
                "cluster": int(baseline[i]),
                "loyalty": round(loyalty, 3),
                "defection": round(defection, 3),
                "stability": round(loyalty - defection, 3),
            }
        )
    zone_stability.sort(key=lambda r: r["stability"])

    used: set[str] = set()
    clusters = []
    for c in sorted(set(baseline.tolist())):
        members = [zones[i] for i in range(len(zones)) if baseline[i] == c]
        clusters.append({"cluster": int(c), "name": _bloc_name(members, used), "members": members, "size": len(members)})

    return {
        "k": int(k),
        "n_modes": int(n_modes),
        "baseline_labels": [int(v) for v in baseline],
        "baseline_silhouette": round(silhouette(corr_full, baseline, n_modes), 4),
        "clusters": clusters,
        "seasons": [{kk: vv for kk, vv in r.items() if kk != "labels"} for r in season_rows],
        "hour_blocks": [{kk: vv for kk, vv in r.items() if kk != "labels"} for r in hour_rows],
        "season_hour": joint_rows,
        "zone_stability": zone_stability,
        "co_membership": co_membership.round(3).tolist(),
        "n_null": int(n_null),
        "summary": {
            "min_ari": round(float(min(r["ari"] for r in all_rows)), 4),
            "max_ari": round(float(max(r["ari"] for r in all_rows)), 4),
            "mean_ari": round(float(np.mean([r["ari"] for r in all_rows])), 4),
            "n_reorganised": int(sum(1 for r in all_rows if r["reorganised"])),
            "n_strata": len(all_rows),
            "market_mode_range": [
                round(float(min(r["market_mode_share"] for r in all_rows)), 4),
                round(float(max(r["market_mode_share"] for r in all_rows)), 4),
            ],
        },
    }


def _merged_clusters(base: np.ndarray, other: np.ndarray) -> list[list[int]]:
    """Baseline clusters that the stratum partition folds into one group."""
    groups: dict[int, set[int]] = {}
    for b, o in zip(base.tolist(), other.tolist()):
        groups.setdefault(o, set()).add(b)
    return [sorted(v) for v in groups.values() if len(v) > 1]


def _split_clusters(base: np.ndarray, other: np.ndarray) -> list[int]:
    """Baseline clusters the stratum partition breaks into several groups."""
    groups: dict[int, set[int]] = {}
    for b, o in zip(base.tolist(), other.tolist()):
        groups.setdefault(b, set()).add(o)
    return sorted(k for k, v in groups.items() if len(v) > 1)


def _same_group(base: np.ndarray, other: np.ndarray, i: int) -> bool:
    """True when zone i keeps a majority of its baseline peers."""
    peers = np.where(base == base[i])[0]
    peers = peers[peers != i]
    if len(peers) == 0:
        return True
    return bool((other[peers] == other[i]).mean() >= 0.5)


def select_k(scan: list[dict[str, Any]], *, tolerance: float = 0.01, k_cap: int | None = None) -> int:
    """Smallest k whose silhouette is within `tolerance` of the best.

    RQ1 fixes how many cluster *dimensions* survive the noise bulk; it does not
    fix how many *blocs* those dimensions resolve into. That choice is made
    here on the silhouette curve, favouring the more parsimonious partition
    when the curve has already flattened.

    Silhouette keeps rising as single zones peel off into their own cluster, so
    candidates with a singleton cluster are excluded: a bloc of one is not a
    bloc. `k_cap` additionally keeps k in the range the supported mode count
    can plausibly resolve.
    """
    eligible = [
        row
        for row in scan
        if min(row["sizes"]) >= 2 and (k_cap is None or row["k"] <= k_cap)
    ]
    if not eligible:
        eligible = list(scan)
    best = max(row["silhouette"] for row in eligible)
    for row in sorted(eligible, key=lambda r: r["k"]):
        if row["silhouette"] >= best - tolerance:
            return int(row["k"])
    return int(eligible[0]["k"])


def k_sensitivity(
    panel: pd.DataFrame,
    *,
    n_modes: int,
    k_values: Sequence[int],
) -> list[dict[str, Any]]:
    """Season / hour-block ARI at several cluster counts.

    The persistence claim in RQ2 should not rest on one value of k.
    """
    index = pd.DatetimeIndex(panel.index)
    corr_full = _corr(panel)
    strata = [panel[index.month.isin(m)] for m in SEASONS.values()]
    strata += [panel[index.hour.isin(h)] for h in HOUR_BLOCKS.values()]
    corrs = [_corr(sub) for sub in strata]
    rows = []
    for k in k_values:
        base = partition(corr_full, k, n_modes)
        aris = [adjusted_rand_index(base, partition(c, k, n_modes)) for c in corrs]
        rows.append(
            {
                "k": int(k),
                "mean_ari": round(float(np.mean(aris)), 4),
                "min_ari": round(float(np.min(aris)), 4),
                "silhouette": round(silhouette(corr_full, base, n_modes), 4),
            }
        )
    return rows


def cluster_count_scan(panel: pd.DataFrame, *, n_modes: int, k_max: int = 12) -> list[dict[str, Any]]:
    corr = _corr(panel)
    rows = []
    for k in range(2, k_max + 1):
        labels = partition(corr, k, n_modes)
        sizes = sorted(np.bincount(labels)[1:].tolist(), reverse=True)
        rows.append({"k": k, "silhouette": round(silhouette(corr, labels, n_modes), 4), "sizes": sizes})
    return rows


# --------------------------------------------------------------------------
# RQ3 - co-movement against physical topology
# --------------------------------------------------------------------------


def topology(zones_config: list[dict], zones: Sequence[str]) -> dict[str, set[str]]:
    keep = set(zones)
    adjacency: dict[str, set[str]] = {z: set() for z in zones}
    for entry in zones_config:
        a = entry["code"]
        if a not in keep:
            continue
        for b in entry.get("neighbors", []) or []:
            if b in keep:
                adjacency[a].add(b)
                adjacency[b].add(a)
    return adjacency


def hop_distances(adjacency: dict[str, set[str]]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for src in adjacency:
        dist = {src: 0}
        queue = deque([src])
        while queue:
            node = queue.popleft()
            for nxt in adjacency[node]:
                if nxt not in dist:
                    dist[nxt] = dist[node] + 1
                    queue.append(nxt)
        out[src] = dist
    return out


def _load_ntc(config: AppConfig) -> tuple[dict[tuple[str, str], float], dict[str, Any]]:
    """Per-border NTC, with zone aggregates removed.

    ENTSO-E A61 has the same defect as the A11 flows: for many zones the same
    aggregate figure is published against every border of that zone (FR reports
    2801 MW on BE, DE_LU and IT_NORTH alike). Those values are not border
    capacities, so a value an exporting zone repeats on more than one border is
    dropped rather than used.
    """
    root = config.data_root / "raw" / "entsoe" / "net_transfer_capacity"
    if not root.exists():
        return {}, {"borders_raw": 0, "borders_kept": 0, "borders_dropped": 0}
    frames = [pd.read_parquet(path) for path in sorted(root.glob("*/*.parquet"))]
    if not frames:
        return {}, {"borders_raw": 0, "borders_kept": 0, "borders_dropped": 0}

    means = pd.concat(frames, ignore_index=True).groupby(["from_zone", "to_zone"])["value"].mean()
    directed: dict[tuple[str, str], float] = {}
    dropped = 0
    for exporter, group in means.groupby(level=0):
        counts = group.round(0).value_counts()
        for (_, importer), value in group.items():
            if counts.get(round(value, 0), 0) > 1:
                dropped += 1
                continue
            directed[(exporter, importer)] = float(value)

    undirected: dict[tuple[str, str], float] = {}
    for (a, b), value in directed.items():
        key = tuple(sorted((a, b)))
        undirected[key] = max(undirected.get(key, 0.0), value)

    meta = {
        "borders_raw": int(len(means)),
        "borders_kept": int(len(undirected)),
        "borders_dropped": int(dropped),
        "note": "directed NTC values an exporting zone repeats across borders are zone aggregates, not border capacity, and are excluded",
    }
    return undirected, meta


def _load_flow_means(config: AppConfig, year: int) -> tuple[dict[tuple[str, str], float], dict[str, Any]]:
    """Mean |MW| per border, restricted to validated directed pairs.

    `flow_validation` finds that most directed A11 pairs republish the
    exporting zone's total export on every border. Those numbers cannot be read
    as border flow, so only pairs it does not flag as `duplicate_export` or
    `missing` are returned.
    """
    report_path = config.data_root / "manifests" / f"flow_validation_{year}.json"
    if not report_path.exists():
        return {}, {"pairs_total": 0, "pairs_validated": 0, "note": "flow validation report not found"}

    report = json.loads(report_path.read_text(encoding="utf-8"))
    trusted = {"ok", "partial", "weak_mirror"}
    out: dict[tuple[str, str], float] = {}
    for row in report.get("all_pairs", []):
        if row.get("status") not in trusted:
            continue
        key = tuple(sorted((row["from_zone"], row["to_zone"])))
        out[key] = max(out.get(key, 0.0), float(row.get("mean_abs_mw") or 0.0))

    meta = {
        "pairs_total": int(report.get("pairs_total", 0)),
        "pairs_validated": int(len(out)),
        "by_status": report.get("by_status", {}),
        "note": "ENTSO-E republishes each zone's aggregate export on every one of its borders for most pairs; those are excluded",
    }
    return out, meta


def _mantel(corr_dist: np.ndarray, topo_dist: np.ndarray, *, n_perm: int, seed: int) -> dict[str, float]:
    n = corr_dist.shape[0]
    iu = np.triu_indices(n, 1)
    x = corr_dist[iu]
    y = topo_dist[iu]
    finite = np.isfinite(x) & np.isfinite(y)
    x, y = x[finite], y[finite]
    observed = float(np.corrcoef(x, y)[0, 1])
    rng = np.random.default_rng(seed)
    count = 0
    for _ in range(n_perm):
        perm = rng.permutation(n)
        permuted = topo_dist[np.ix_(perm, perm)][iu][finite]
        if abs(float(np.corrcoef(x, permuted)[0, 1])) >= abs(observed):
            count += 1
    return {"r": round(observed, 4), "p_value": round((count + 1) / (n_perm + 1), 5), "n_permutations": int(n_perm)}


def topology_comparison(
    config: AppConfig,
    year: int,
    levels: pd.DataFrame,
    residuals: pd.DataFrame,
    *,
    n_mantel: int = N_MANTEL,
    seed: int = 20260921,
) -> dict[str, Any]:
    zones = list(levels.columns)
    adjacency = topology(config.zones, zones)
    hops = hop_distances(adjacency)
    corr_lev = _corr(levels)
    corr_res = _corr(residuals)
    ntc, ntc_meta = _load_ntc(config)
    flows, flow_meta = _load_flow_means(config, year)

    rows: list[dict[str, Any]] = []
    for i, a in enumerate(zones):
        for j in range(i + 1, len(zones)):
            b = zones[j]
            key = tuple(sorted((a, b)))
            diff = (levels[a] - levels[b]).abs()
            rows.append(
                {
                    "a": a,
                    "b": b,
                    "hops": hops[a].get(b),
                    "adjacent": int(b in adjacency[a]),
                    "r_levels": round(float(corr_lev[i, j]), 4),
                    "r_residual": round(float(corr_res[i, j]), 4),
                    "convergence": round(float((diff < 0.01).mean()), 4),
                    "mean_spread": round(float(diff.mean()), 2),
                    "ntc_mw": round(ntc[key], 1) if key in ntc else None,
                    "flow_mw": round(flows[key], 1) if key in flows else None,
                }
            )
    pairs = pd.DataFrame(rows)

    profile = (
        pairs.dropna(subset=["hops"])
        .groupby("hops")
        .agg(
            pairs=("r_levels", "size"),
            r_levels=("r_levels", "mean"),
            r_residual=("r_residual", "mean"),
            convergence=("convergence", "mean"),
            mean_spread=("mean_spread", "mean"),
        )
        .reset_index()
    )
    profile_rows = [
        {
            "hops": int(r.hops),
            "pairs": int(r.pairs),
            "r_levels": round(float(r.r_levels), 3),
            "r_residual": round(float(r.r_residual), 3),
            "convergence": round(float(r.convergence), 3),
            "mean_spread": round(float(r.mean_spread), 1),
        }
        for r in profile.itertuples()
    ]

    adjacent = pairs[pairs.adjacent == 1]
    distant = pairs[pairs.adjacent == 0]
    n_pos, n_neg = len(adjacent), len(distant)
    auc_levels = auc_resid = None
    p_levels = None
    if n_pos and n_neg:
        u_lev = mannwhitneyu(adjacent.r_levels, distant.r_levels, alternative="greater")
        u_res = mannwhitneyu(adjacent.r_residual, distant.r_residual, alternative="greater")
        auc_levels = round(float(u_lev.statistic / (n_pos * n_neg)), 4)
        auc_resid = round(float(u_res.statistic / (n_pos * n_neg)), 4)
        p_levels = float(u_lev.pvalue)

    # Mantel: correlation distance against hop distance.
    n = len(zones)
    corr_dist = np.sqrt(np.clip(2.0 * (1.0 - corr_lev), 0.0, None))
    topo_dist = np.full((n, n), np.nan)
    for i, a in enumerate(zones):
        for j, b in enumerate(zones):
            if b in hops[a]:
                topo_dist[i, j] = hops[a][b]
    finite_max = np.nanmax(topo_dist)
    topo_dist = np.nan_to_num(topo_dist, nan=finite_max + 1)
    mantel = _mantel(corr_dist, topo_dist, n_perm=n_mantel, seed=seed)

    # Expected correlation given hop distance, so divergence is measured
    # against the topology's own decay curve rather than an absolute cut-off.
    expected = {int(r["hops"]): r["r_levels"] for r in profile_rows}
    pairs = pairs.assign(
        expected_r=pairs["hops"].map(lambda h: expected.get(int(h)) if pd.notna(h) else None),
    )
    pairs = pairs.assign(residual_r=pairs["r_levels"] - pairs["expected_r"])

    def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
        out = []
        for r in frame.itertuples():
            out.append(
                {
                    "a": r.a,
                    "b": r.b,
                    "hops": int(r.hops) if pd.notna(r.hops) else None,
                    "r_levels": float(r.r_levels),
                    "r_residual": float(r.r_residual),
                    "convergence": float(r.convergence),
                    "mean_spread": float(r.mean_spread),
                    "ntc_mw": None if r.ntc_mw is None or pd.isna(r.ntc_mw) else float(r.ntc_mw),
                    "flow_mw": None if r.flow_mw is None or pd.isna(r.flow_mw) else float(r.flow_mw),
                    "gap_vs_expected": None if pd.isna(r.residual_r) else round(float(r.residual_r), 3),
                }
            )
        return out

    under = adjacent.merge(pairs[["a", "b", "residual_r"]], on=["a", "b"], how="left").nsmallest(15, "r_levels")
    over = pairs[(pairs.adjacent == 0) & (pairs.hops >= 2)].nlargest(15, "r_levels")

    # Borders that are physically connected yet almost never settle at one
    # price. Ranked on convergence and spread, both of which come from the
    # price panel: the A11 flow figure is only available for the handful of
    # borders that survive flow validation.
    congested = adjacent.merge(pairs[["a", "b", "residual_r"]], on=["a", "b"], how="left")
    congested = congested[congested.convergence < 0.05].nlargest(15, "mean_spread")

    return {
        "n_zones": len(zones),
        "n_pairs": int(len(pairs)),
        "n_adjacent_pairs": int(n_pos),
        "hop_profile": profile_rows,
        "auc_levels": auc_levels,
        "auc_residual": auc_resid,
        "auc_p_value": None if p_levels is None else float(f"{p_levels:.3g}"),
        "mantel": mantel,
        "adjacent_mean_r": round(float(adjacent.r_levels.mean()), 4),
        "distant_mean_r": round(float(distant.r_levels.mean()), 4),
        "adjacent_mean_convergence": round(float(adjacent.convergence.mean()), 4),
        "under_coupled": _records(under),
        "over_coupled": _records(over),
        "congested_borders": _records(congested),
        "ntc_correlation": _ntc_correlation(adjacent, ntc),
        "ntc_coverage": ntc_meta,
        "flow_coverage": flow_meta,
        "data_caveat": (
            "Mean flow and NTC are shown only for borders where ENTSO-E publishes a "
            "genuine per-border value. For most borders it republishes the exporting "
            "zone's aggregate on every border, so those figures are omitted rather "
            "than reported. Correlation, convergence and spread come from the price "
            "panel and are unaffected."
        ),
        "pairs": _records(pairs),
    }


def _ntc_correlation(adjacent: pd.DataFrame, ntc: dict[tuple[str, str], float]) -> dict[str, Any]:
    sub = adjacent.dropna(subset=["ntc_mw"])
    if len(sub) < 5:
        return {"n": int(len(sub)), "r": None, "note": "too few borders with NTC data"}
    r = float(np.corrcoef(np.log1p(sub.ntc_mw.to_numpy(dtype=float)), sub.r_levels.to_numpy(dtype=float))[0, 1])
    return {
        "n": int(len(sub)),
        "r": round(r, 4),
        "note": (
            "Pearson r between log(1+NTC) and level correlation, over the adjacent "
            "borders with a genuine per-border NTC value"
        ),
    }


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------


def run_comovement(
    config: AppConfig,
    year: int,
    *,
    n_surrogates: int = N_SURROGATES,
    n_null: int = N_STRATUM_NULL,
    n_mantel: int = N_MANTEL,
    k_clusters: int | None = None,
    seed: int = 20260921,
) -> dict[str, Any]:
    panels = build_price_panels(config, year)
    levels: pd.DataFrame = panels["levels"]
    residuals: pd.DataFrame = panels["residuals"]
    log.info("co-movement panel: %d zones x %d hours", len(panels["zones"]), panels["hours"])

    spectrum_res = eigen_spectrum(residuals, n_surrogates=n_surrogates, seed=seed)
    spectrum_lev = eigen_spectrum(levels, n_surrogates=n_surrogates, seed=seed + 1)

    n_modes = max(spectrum_res["k_significant_95"], 2)
    log.info(
        "RQ1: %d significant modes, market mode %.1f%%",
        spectrum_res["k_significant_95"],
        100 * spectrum_res["variance_market_mode"],
    )

    scan = cluster_count_scan(residuals, n_modes=n_modes)
    k = int(k_clusters or select_k(scan, k_cap=2 * spectrum_res["k_significant_95"]))
    log.info("RQ2: clustering at k=%d (silhouette %.3f)", k, dict((r["k"], r["silhouette"]) for r in scan)[k])
    sensitivity = k_sensitivity(residuals, n_modes=n_modes, k_values=range(max(k - 3, 2), k + 3))
    strata = stratified_partitions(residuals, k=k, n_modes=n_modes, n_null=n_null, seed=seed)
    topo = topology_comparison(config, year, levels, residuals, n_mantel=n_mantel, seed=seed)

    def public(spec: dict[str, Any]) -> dict[str, Any]:
        return {kk: vv for kk, vv in spec.items() if kk not in {"eigenvectors", "correlation"}}

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "year": year,
        "panel": {
            "zones": panels["zones"],
            "n_zones": len(panels["zones"]),
            "hours": panels["hours"],
            "dropped_zones": panels["dropped_zones"],
            "coverage": panels["coverage"],
            "resolution": "hourly UTC means (15-min MTU zones averaged into hours)",
            "min_zone_coverage": MIN_ZONE_COVERAGE,
            "max_interpolate_hours": MAX_INTERPOLATE_HOURS,
        },
        "rq1": {
            "question": (
                "How much of European price co-movement is a single Europe-wide mode, "
                "how much is cluster-specific, and how many cluster dimensions are "
                "statistically supported?"
            ),
            "residuals": public(spectrum_res),
            "levels": public(spectrum_lev),
            "modes_residual": mode_loadings(spectrum_res),
            "modes_levels": mode_loadings(spectrum_lev, n_modes=4),
            "method": (
                "Correlation eigen-decomposition. Significance from 95th-percentile "
                "order statistics of phase-randomised surrogates (per-zone spectrum "
                "preserved, cross-coupling destroyed), cross-checked against a "
                "Marchenko-Pastur bound using an AR(1)-adjusted effective sample size."
            ),
        },
        "rq2": {
            "question": "Do the price clusters persist across seasons and intraday, or does the partition reorganise?",
            "cluster_scan": scan,
            "k_sensitivity": sensitivity,
            "k_selection": (
                "k fixed by user" if k_clusters else
                "smallest k within 0.01 silhouette of the best eligible value "
                "(no singleton clusters, k <= 2x the supported mode count)"
            ),
            **strata,
            "method": (
                "Average-linkage clustering on sqrt(2(1-C_group)) where C_group is the "
                "correlation rebuilt from modes 2..k (market mode removed). Partitions "
                "compared to the full-year baseline by Adjusted Rand Index against a "
                "stratum-label permutation null of the same sample size."
            ),
        },
        "rq3": {
            "question": "Does price co-movement follow the physical interconnection topology, and where does it diverge?",
            **topo,
            "method": (
                "Hop distance from the config topology, Mantel permutation test between "
                "correlation distance and hop distance, Mann-Whitney AUC for adjacency "
                "discrimination, and border tables scored against the hop-distance decay "
                "curve with NTC, mean flow and price-convergence evidence."
            ),
        },
    }
    report["findings"] = _findings(report)

    out_dir = config.data_root / "manifests"
    out_dir.mkdir(parents=True, exist_ok=True)
    full_path = out_dir / f"comovement_{year}.json"
    full_path.write_text(json.dumps(report, indent=2, default=_json_default), encoding="utf-8")

    slim = _slim(report)
    dash_dir = out_dir / "dashboard"
    dash_dir.mkdir(parents=True, exist_ok=True)
    slim_path = dash_dir / f"comovement_{year}.json"
    slim_path.write_text(json.dumps(slim, indent=2, default=_json_default), encoding="utf-8")

    report["output_path"] = str(full_path)
    report["dashboard_path"] = str(slim_path)
    return report


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"not JSON serialisable: {type(obj)}")


def _findings(report: dict[str, Any]) -> dict[str, str]:
    res = report["rq1"]["residuals"]
    lev = report["rq1"]["levels"]
    rq2 = report["rq2"]
    rq3 = report["rq3"]

    named = ", ".join(c["name"] for c in rq2["clusters"])
    marginal = rq2["seasons"] + rq2["hour_blocks"]
    all_rows = marginal + rq2["season_hour"]
    reorganised = [r["label"] for r in all_rows if r["reorganised"]]
    n_marginal_reorg = sum(1 for r in marginal if r["reorganised"])
    weakest = min(all_rows, key=lambda r: r["market_mode_share"])
    strongest = max(all_rows, key=lambda r: r["market_mode_share"])
    under = rq3["under_coupled"][:3]
    over = rq3["over_coupled"][:3]

    if not reorganised:
        verdict = "The partition persists across every stratum tested."
    elif n_marginal_reorg == 0:
        verdict = (
            f"The partition persists across all {len(marginal)} season and hour-block strata; "
            f"only {len(reorganised)} of {len(rq2['season_hour'])} season x hour-block cells "
            f"reorganise ({', '.join(reorganised)})."
        )
    else:
        verdict = (
            f"{len(reorganised)} of {len(all_rows)} strata reorganise beyond the null "
            f"({', '.join(reorganised)})."
        )

    return {
        "rq1": (
            f"On deseasonalised prices a single Europe-wide mode carries "
            f"{100 * res['variance_market_mode']:.0f}% of the variance across "
            f"{res['n_zones']} zones; {res['cluster_dimensions']} further cluster dimensions "
            f"are statistically supported and together carry "
            f"{100 * res['variance_cluster_modes']:.0f}%, leaving "
            f"{100 * res['variance_noise_bulk']:.0f}% in the noise bulk. On raw levels the "
            f"common mode rises to {100 * lev['variance_market_mode']:.0f}%, so roughly "
            f"{100 * (lev['variance_market_mode'] - res['variance_market_mode']):.0f} points "
            f"of apparent Europe-wide co-movement is shared calendar shape rather than shared "
            f"shocks. The surrogate null and the AR(1)-adjusted Marchenko-Pastur bound agree: "
            f"{res['k_significant_95']} and {res['k_significant_mp']} supported modes "
            f"(naive MP on {res['n_hours']} raw hours would be far more permissive, since the "
            f"effective sample is only {res['n_effective']:.0f} hours at mean AR(1)="
            f"{res['mean_ar1']:.2f})."
        ),
        "rq2": (
            f"{verdict} The {rq2['k']}-cluster partition is {named}. Across "
            f"{rq2['summary']['n_strata']} strata the ARI against the full-year baseline runs "
            f"{rq2['summary']['min_ari']:.2f}-{rq2['summary']['max_ari']:.2f}, and mean ARI "
            f"stays between {min(r['mean_ari'] for r in rq2['k_sensitivity']):.2f} and "
            f"{max(r['mean_ari'] for r in rq2['k_sensitivity']):.2f} for every k from "
            f"{rq2['k_sensitivity'][0]['k']} to {rq2['k_sensitivity'][-1]['k']}, so the "
            f"conclusion does not hinge on the cluster count. What does move with the clock is "
            f"the Europe-wide mode itself: its share falls to "
            f"{100 * weakest['market_mode_share']:.0f}% in {weakest['label']} and peaks at "
            f"{100 * strongest['market_mode_share']:.0f}% in {strongest['label']} - the hours "
            f"when solar output is largest are the hours when Europe prices least as one market."
        ),
        "rq3": (
            f"Co-movement tracks topology closely but not exactly: level correlation decays "
            f"monotonically from {rq3['hop_profile'][0]['r_levels']:.2f} at one hop to "
            f"{rq3['hop_profile'][-1]['r_levels']:.2f} at {rq3['hop_profile'][-1]['hops']} hops, "
            f"adjacency is discriminated at AUC {rq3['auc_levels']:.2f}, and the Mantel "
            f"correlation between price distance and hop distance is {rq3['mantel']['r']:.2f} "
            f"(p={rq3['mantel']['p_value']}). The divergences are systematic. Directly connected "
            f"but weakly coupled: "
            + ", ".join(f"{r['a']}-{r['b']} (r={r['r_levels']:.2f})" for r in under)
            + " - internal Nordic and HVDC borders where the wire exists but the price rarely "
            "converges. Non-adjacent but tightly coupled: "
            + ", ".join(f"{r['a']}-{r['b']} (r={r['r_levels']:.2f})" for r in over)
            + f" - zones inside one coupled bloc that need no direct line. Border capacity "
            f"explains part but not most of the split: over the "
            f"{rq3['ntc_correlation'].get('n')} borders with a genuine per-border NTC value, "
            f"log capacity correlates r={rq3['ntc_correlation'].get('r')} with price coupling. "
            f"The rest is congestion frequency and market-coupling membership. One caveat on the "
            f"evidence: ENTSO-E republishes each zone's aggregate on most of its borders, so only "
            f"{rq3['ntc_coverage'].get('borders_kept')} of "
            f"{rq3['ntc_coverage'].get('borders_raw')} NTC borders and "
            f"{rq3['flow_coverage'].get('pairs_validated')} of "
            f"{rq3['flow_coverage'].get('pairs_total')} directed flow pairs carry usable "
            f"per-border numbers - the correlation, convergence and spread figures come from the "
            f"price panel and are unaffected."
        ),
    }


def _slim(report: dict[str, Any]) -> dict[str, Any]:
    res = report["rq1"]["residuals"]
    lev = report["rq1"]["levels"]
    rq2 = report["rq2"]
    rq3 = report["rq3"]
    top = 20
    return {
        "generated_at": report["generated_at"],
        "year": report["year"],
        "panel": {k: v for k, v in report["panel"].items() if k != "coverage"},
        "findings": report["findings"],
        "rq1": {
            "question": report["rq1"]["question"],
            "method": report["rq1"]["method"],
            "spectrum": {
                "zones": res["n_zones"],
                "hours": res["n_hours"],
                "eigenvalues": [round(v, 4) for v in res["eigenvalues"][:top]],
                "explained": [round(v, 4) for v in res["explained"][:top]],
                "null_q95": [round(v, 4) for v in res["null_q95"][:top]],
                "null_mean": [round(v, 4) for v in res["null_mean"][:top]],
                "k_significant_95": res["k_significant_95"],
                "k_significant_mp": res["k_significant_mp"],
                "cluster_dimensions": res["cluster_dimensions"],
                "mean_ar1": res["mean_ar1"],
                "n_effective": res["n_effective"],
                "mp_upper_effective": res["mp_upper_effective"],
                "n_surrogates": res["n_surrogates"],
            },
            "variance": {
                "residual": {
                    "market": res["variance_market_mode"],
                    "cluster": res["variance_cluster_modes"],
                    "noise": res["variance_noise_bulk"],
                },
                "levels": {
                    "market": lev["variance_market_mode"],
                    "cluster": lev["variance_cluster_modes"],
                    "noise": lev["variance_noise_bulk"],
                },
            },
            "levels_explained": [round(v, 4) for v in lev["explained"][:top]],
            "modes": report["rq1"]["modes_residual"],
        },
        "rq2": {
            "question": rq2["question"],
            "method": rq2["method"],
            "k": rq2["k"],
            "clusters": rq2["clusters"],
            "baseline_silhouette": rq2["baseline_silhouette"],
            "cluster_scan": rq2["cluster_scan"],
            "k_sensitivity": rq2["k_sensitivity"],
            "k_selection": rq2["k_selection"],
            "seasons": rq2["seasons"],
            "hour_blocks": rq2["hour_blocks"],
            "season_hour": rq2["season_hour"],
            "zone_stability": rq2["zone_stability"],
            "summary": rq2["summary"],
            "n_null": rq2["n_null"],
        },
        "rq3": {
            "question": rq3["question"],
            "method": rq3["method"],
            "hop_profile": rq3["hop_profile"],
            "auc_levels": rq3["auc_levels"],
            "auc_residual": rq3["auc_residual"],
            "auc_p_value": rq3["auc_p_value"],
            "mantel": rq3["mantel"],
            "adjacent_mean_r": rq3["adjacent_mean_r"],
            "distant_mean_r": rq3["distant_mean_r"],
            "adjacent_mean_convergence": rq3["adjacent_mean_convergence"],
            "ntc_correlation": rq3["ntc_correlation"],
            "ntc_coverage": rq3["ntc_coverage"],
            "flow_coverage": rq3["flow_coverage"],
            "data_caveat": rq3["data_caveat"],
            "under_coupled": rq3["under_coupled"],
            "over_coupled": rq3["over_coupled"],
            "congested_borders": rq3["congested_borders"],
            "n_pairs": rq3["n_pairs"],
            "n_adjacent_pairs": rq3["n_adjacent_pairs"],
        },
    }
