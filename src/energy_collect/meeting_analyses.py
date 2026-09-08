"""
Meeting-point analyses on the 2025 ENTSO-E panel.

1. TE reversals across HOD / DOW / season / month
2. Multiplex dependency structure
3. Price coupling vs physical flow mismatch
4. Nested Year → Month → Week → HOD TE (example corridors)
5. Grid / plant network overlay
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from itertools import combinations
from typing import Any

import numpy as np
import pandas as pd

from energy_collect.config import AppConfig
from energy_collect.graph import all_price_coupling_edges, zone_country
from energy_collect.static_merge import _load_gem_capacity
from energy_collect.transfer_entropy import pair_te_both
from energy_collect.utils.gem_countries import gem_country_to_iso2
from energy_collect.utils.zones import border_pairs

DEFAULT_NESTED_ZONES = ["FR", "ES", "PT", "DE_LU", "AT", "CH", "IT_NORTH", "NO_2"]

SEASON_MONTHS = {
    "DJF": {12, 1, 2},
    "MAM": {3, 4, 5},
    "JJA": {6, 7, 8},
    "SON": {9, 10, 11},
}

MISMATCH_LABELS = {
    "congested_trade": "High physical flow, weak price coupling",
    "paper_coupling": "Strong price coupling, weak physical flow",
    "aligned_strong": "Strong flow and strong price coupling",
    "informational": "Directed TE without matching flow or Pearson r",
    "weak": "Weak on all layers",
}


def _load_prices(config: AppConfig, year: int, *, deseasonalised: bool) -> pd.DataFrame:
    name = f"prices_deseasonalised_{year}.parquet" if deseasonalised else f"prices_{year}.parquet"
    path = config.data_root / "processed" / "entsoe" / name
    if deseasonalised and not path.exists():
        from energy_collect.seasonality import run_seasonality_decomposition

        run_seasonality_decomposition(config, year, dataset="prices")
    df = pd.read_parquet(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def _load_flows(config: AppConfig, year: int) -> pd.DataFrame:
    path = config.data_root / "processed" / "entsoe" / f"flows_{year}.parquet"
    df = pd.read_parquet(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def _wide_prices(prices: pd.DataFrame) -> pd.DataFrame:
    return prices.pivot_table(index="timestamp", columns="zone", values="value", aggfunc="mean")


def _undirected_key(a: str, b: str) -> str:
    x, y = sorted((a, b))
    return f"{x}|{y}"


def _neighbor_undirected(zones_config: list[dict]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    pairs: list[tuple[str, str]] = []
    for p in border_pairs(zones_config):
        key = _undirected_key(p.from_zone, p.to_zone)
        if key in seen:
            continue
        seen.add(key)
        a, b = key.split("|")
        pairs.append((a, b))
    return pairs


def _te_on_mask(
    wide: pd.DataFrame,
    a: str,
    b: str,
    mask: pd.Series,
    *,
    min_len: int,
    n_bins: int,
    seed: int,
) -> dict[str, float] | None:
    if a not in wide.columns or b not in wide.columns:
        return None
    sub = wide.loc[mask, [a, b]].dropna()
    te_b_to_a, te_a_to_b = pair_te_both(
        sub[a].to_numpy(),
        sub[b].to_numpy(),
        method="discrete",
        effective=False,
        n_bins=n_bins,
        seed=seed,
        min_len=min_len,
    )
    if np.isnan(te_b_to_a) and np.isnan(te_a_to_b):
        return None
    te_ab = 0.0 if np.isnan(te_a_to_b) else float(te_a_to_b)
    te_ba = 0.0 if np.isnan(te_b_to_a) else float(te_b_to_a)
    return {
        "te_a_to_b": round(te_ab, 5),
        "te_b_to_a": round(te_ba, 5),
        "net_a_minus_b": round(te_ab - te_ba, 5),
        "leader": a if te_ab >= te_ba else b,
        "n": int(len(sub)),
    }


def _stratum_masks(index: pd.DatetimeIndex) -> dict[str, dict[str, pd.Series]]:
    ts = pd.DatetimeIndex(index)

    def m(cond: Any) -> pd.Series:
        return pd.Series(np.asarray(cond), index=ts)

    hod = {f"{h:02d}": m(ts.hour == h) for h in range(24)}
    dow = {
        "weekday": m(ts.dayofweek < 5),
        "weekend": m(ts.dayofweek >= 5),
    }
    seasons = {name: m(ts.month.isin(months)) for name, months in SEASON_MONTHS.items()}
    months = {f"{mth:02d}": m(ts.month == mth) for mth in range(1, 13)}
    return {"hod": hod, "dow": dow, "season": seasons, "moy": months}


def detect_reversals(
    pair_results: dict[str, dict[str, Any]],
    *,
    min_abs_net: float = 0.03,
) -> list[dict[str, Any]]:
    """Flag undirected pairs whose TE leader flips across bins of one regime."""
    reversals: list[dict[str, Any]] = []
    for pair_key, payload in pair_results.items():
        bins = payload.get("bins", {})
        signed = []
        for label, row in bins.items():
            net = float(row.get("net_a_minus_b", 0.0))
            if abs(net) < min_abs_net:
                continue
            signed.append((label, net, row.get("leader")))
        if len(signed) < 2:
            continue
        signs = {np.sign(n) for _, n, _ in signed}
        if 1.0 in signs and -1.0 in signs:
            a, b = pair_key.split("|")
            pos = [lab for lab, n, _ in signed if n > 0]
            neg = [lab for lab, n, _ in signed if n < 0]
            if not pos or not neg:
                continue
            reversals.append(
                {
                    "pair": pair_key,
                    "a": a,
                    "b": b,
                    "a_leads_in": pos,
                    "b_leads_in": neg,
                    "n_bins_used": len(signed),
                }
            )
    reversals.sort(key=lambda r: -r["n_bins_used"])
    return reversals


def compute_te_regimes(
    wide: pd.DataFrame,
    pairs: list[tuple[str, str]],
    *,
    n_bins: int = 6,
    min_len: int = 80,
    min_abs_net: float = 0.03,
) -> dict[str, Any]:
    masks = _stratum_masks(wide.index)
    regime_out: dict[str, Any] = {}
    seed = 11
    for regime, mask_map in masks.items():
        pair_results: dict[str, dict[str, Any]] = {}
        for a, b in pairs:
            bins: dict[str, Any] = {}
            for label, mask in mask_map.items():
                row = _te_on_mask(wide, a, b, mask, min_len=min_len, n_bins=n_bins, seed=seed)
                seed += 2
                if row:
                    bins[label] = row
            if bins:
                pair_results[f"{a}|{b}"] = {"a": a, "b": b, "bins": bins}
        reversals = detect_reversals(pair_results, min_abs_net=min_abs_net)
        # Compact dashboard payload: reversals + a few example bin tables
        examples = []
        for rev in reversals[:12]:
            examples.append(
                {
                    **rev,
                    "bins": pair_results[rev["pair"]]["bins"],
                }
            )
        regime_out[regime] = {
            "pairs_estimated": len(pair_results),
            "reversals": reversals,
            "reversal_count": len(reversals),
            "examples": examples,
        }
    return regime_out


def compute_nested_te(
    wide: pd.DataFrame,
    zones: list[str],
    *,
    n_bins: int = 6,
    min_len_year: int = 400,
    min_len_month: int = 200,
    min_len_week: int = 80,
    min_len_hod: int = 80,
) -> dict[str, Any]:
    present = [z for z in zones if z in wide.columns]
    pairs = list(combinations(present, 2))
    idx = wide.index
    iso = pd.DatetimeIndex(idx)

    def run_pairs(mask: pd.Series, min_len: int, seed0: int) -> list[dict[str, Any]]:
        rows = []
        seed = seed0
        for a, b in pairs:
            row = _te_on_mask(wide, a, b, mask, min_len=min_len, n_bins=n_bins, seed=seed)
            seed += 2
            if not row:
                continue
            rows.append({"a": a, "b": b, **row})
        return rows

    year_mask = pd.Series(True, index=wide.index)
    year_rows = run_pairs(year_mask, min_len_year, 100)

    month_avg: dict[str, list[float]] = defaultdict(list)
    month_detail: list[dict[str, Any]] = []
    for m in range(1, 13):
        mask = iso.month == m
        rows = run_pairs(mask, min_len_month, 200 + m)
        for r in rows:
            key = _undirected_key(r["a"], r["b"])
            month_avg[key + "|ab"].append(r["te_a_to_b"])
            month_avg[key + "|ba"].append(r["te_b_to_a"])
        month_detail.append({"month": m, "pairs": len(rows)})

    week_avg: dict[str, list[float]] = defaultdict(list)
    weeks_used = 0
    week_ids = pd.Index(iso.isocalendar().week)
    for week in sorted(week_ids.unique()):
        mask = (week_ids == week).to_numpy()
        if int(np.sum(mask)) < min_len_week:
            continue
        weeks_used += 1
        rows = run_pairs(pd.Series(mask, index=wide.index), min_len_week, 400 + int(week))
        for r in rows:
            key = _undirected_key(r["a"], r["b"])
            week_avg[key + "|ab"].append(r["te_a_to_b"])
            week_avg[key + "|ba"].append(r["te_b_to_a"])

    hod_avg: dict[str, list[float]] = defaultdict(list)
    hod_net: dict[str, list[float]] = defaultdict(list)
    for h in range(24):
        mask = iso.hour == h
        rows = run_pairs(mask, min_len_hod, 700 + h)
        for r in rows:
            key = _undirected_key(r["a"], r["b"])
            hod_avg[key + "|ab"].append(r["te_a_to_b"])
            hod_avg[key + "|ba"].append(r["te_b_to_a"])
            hod_net[key].append(r["net_a_minus_b"])

    scale_table: list[dict[str, Any]] = []
    for r in year_rows:
        key = _undirected_key(r["a"], r["b"])
        mean_m_ab = float(np.mean(month_avg.get(key + "|ab", [np.nan])))
        mean_m_ba = float(np.mean(month_avg.get(key + "|ba", [np.nan])))
        mean_w_ab = float(np.mean(week_avg.get(key + "|ab", [np.nan])))
        mean_w_ba = float(np.mean(week_avg.get(key + "|ba", [np.nan])))
        mean_h_ab = float(np.mean(hod_avg.get(key + "|ab", [np.nan])))
        mean_h_ba = float(np.mean(hod_avg.get(key + "|ba", [np.nan])))
        year_ab, year_ba = r["te_a_to_b"], r["te_b_to_a"]
        scale_table.append(
            {
                "a": r["a"],
                "b": r["b"],
                "year_a_to_b": year_ab,
                "year_b_to_a": year_ba,
                "month_avg_a_to_b": None if np.isnan(mean_m_ab) else round(mean_m_ab, 5),
                "month_avg_b_to_a": None if np.isnan(mean_m_ba) else round(mean_m_ba, 5),
                "week_avg_a_to_b": None if np.isnan(mean_w_ab) else round(mean_w_ab, 5),
                "week_avg_b_to_a": None if np.isnan(mean_w_ba) else round(mean_w_ba, 5),
                "hod_avg_a_to_b": None if np.isnan(mean_h_ab) else round(mean_h_ab, 5),
                "hod_avg_b_to_a": None if np.isnan(mean_h_ba) else round(mean_h_ba, 5),
                "year_leader": r["leader"],
                "month_avg_leader": r["a"] if mean_m_ab >= mean_m_ba else r["b"],
                "leader_agrees_month": (r["a"] if year_ab >= year_ba else r["b"])
                == (r["a"] if mean_m_ab >= mean_m_ba else r["b"]),
                "hod_net_series": [round(v, 4) for v in hod_net.get(key, [])],
            }
        )
    scale_table.sort(key=lambda x: -(x["year_a_to_b"] + x["year_b_to_a"]))
    n_agree = sum(1 for r in scale_table if r["leader_agrees_month"])
    return {
        "zones": present,
        "pair_count": len(pairs),
        "weeks_used": weeks_used,
        "year_pairs": len(year_rows),
        "months_with_pairs": month_detail,
        "leader_agreement_year_vs_month_avg": n_agree,
        "scale_table": scale_table,
        "note": (
            "Discrete Schreiber TE on regime-subsampled hours. "
            "HOD lag-1 is the previous calendar day at the same hour."
        ),
    }


def classify_mismatch(
    *,
    mean_abs_mw: float,
    pearson_r: float | None,
    te_max: float | None,
    flow_high: float,
    r_high: float,
    te_high: float,
) -> str:
    r = 0.0 if pearson_r is None or np.isnan(pearson_r) else abs(float(pearson_r))
    te = 0.0 if te_max is None or np.isnan(te_max) else float(te_max)
    high_flow = mean_abs_mw >= flow_high
    high_r = r >= r_high
    high_te = te >= te_high
    if high_flow and high_r:
        return "aligned_strong"
    if high_flow and not high_r:
        return "congested_trade"
    if high_r and not high_flow:
        return "paper_coupling"
    if high_te and not high_flow and not high_r:
        return "informational"
    return "weak"


def compute_price_flow_mismatch(
    prices: pd.DataFrame,
    flows: pd.DataFrame,
    te_edges: list[dict[str, Any]],
    pairs: list[tuple[str, str]],
    *,
    r_high: float = 0.85,
    te_high: float = 0.02,
) -> dict[str, Any]:
    corr_edges = {
        _undirected_key(e["from"], e["to"]): float(e["weight"])
        for e in all_price_coupling_edges(prices, threshold_r=0.0)
    }
    flow_stats: dict[str, dict[str, float]] = {}
    grouped = flows.groupby(["from_zone", "to_zone"])["value"]
    for (frm, to), ser in grouped:
        key = _undirected_key(frm, to)
        abs_mean = float(np.abs(ser).mean())
        prev = flow_stats.get(key)
        if prev is None or abs_mean > prev["mean_abs_mw"]:
            flow_stats[key] = {
                "mean_abs_mw": abs_mean,
                "mean_mw": float(ser.mean()),
                "from": frm,
                "to": to,
            }

    te_max: dict[str, float] = defaultdict(float)
    te_dirs: dict[str, dict[str, float]] = defaultdict(dict)
    for e in te_edges:
        key = _undirected_key(e["from"], e["to"])
        te_max[key] = max(te_max[key], float(e.get("te", 0)))
        te_dirs[key][f"{e['from']}->{e['to']}"] = float(e.get("te", 0))

    mw_values = [flow_stats[k]["mean_abs_mw"] for k in flow_stats]
    flow_high = float(np.median(mw_values)) if mw_values else 500.0

    rows: list[dict[str, Any]] = []
    for a, b in pairs:
        key = _undirected_key(a, b)
        flow = flow_stats.get(key, {"mean_abs_mw": 0.0, "mean_mw": 0.0})
        r = corr_edges.get(key)
        te = te_max.get(key, 0.0)
        kind = classify_mismatch(
            mean_abs_mw=flow["mean_abs_mw"],
            pearson_r=r,
            te_max=te,
            flow_high=flow_high,
            r_high=r_high,
            te_high=te_high,
        )
        rows.append(
            {
                "a": a,
                "b": b,
                "mean_abs_mw": round(float(flow["mean_abs_mw"]), 1),
                "pearson_r": None if r is None else round(float(r), 4),
                "te_max": round(float(te), 5),
                "te_directions": te_dirs.get(key, {}),
                "class": kind,
                "class_label": MISMATCH_LABELS[kind],
            }
        )
    rows.sort(key=lambda x: -x["mean_abs_mw"])
    counts = defaultdict(int)
    for r in rows:
        counts[r["class"]] += 1
    highlights = [r for r in rows if r["class"] == "congested_trade"][:8]
    fr_es = next((r for r in rows if {r["a"], r["b"]} == {"FR", "ES"}), None)
    return {
        "thresholds": {
            "flow_high_mw": round(flow_high, 1),
            "r_high": r_high,
            "te_high": te_high,
            "flow_high_rule": "median mean |MW| across borders with flow data",
        },
        "counts": dict(counts),
        "n_borders": len(rows),
        "highlights_congested_trade": highlights,
        "fr_es": fr_es,
        "borders": rows,
    }


def _strength_table(edges: list[tuple[str, str, float]], nodes: list[str]) -> list[dict[str, Any]]:
    strength: dict[str, float] = {n: 0.0 for n in nodes}
    degree: dict[str, int] = {n: 0 for n in nodes}
    for a, b, w in edges:
        if a not in strength or b not in strength:
            continue
        strength[a] += abs(w)
        strength[b] += abs(w)
        degree[a] += 1
        degree[b] += 1
    rows = [
        {"zone": z, "strength": round(strength[z], 4), "degree": degree[z]}
        for z in nodes
    ]
    rows.sort(key=lambda r: -r["strength"])
    return rows


def _components(edges: list[tuple[str, str]], nodes: list[str]) -> list[list[str]]:
    adj: dict[str, set[str]] = {n: set() for n in nodes}
    for a, b in edges:
        if a in adj and b in adj:
            adj[a].add(b)
            adj[b].add(a)
    seen: set[str] = set()
    comps: list[list[str]] = []
    for n in nodes:
        if n in seen:
            continue
        stack = [n]
        seen.add(n)
        comp = []
        while stack:
            u = stack.pop()
            comp.append(u)
            for v in adj[u]:
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
        comps.append(sorted(comp))
    comps.sort(key=len, reverse=True)
    return comps


def compute_dependency_structure(
    graph: dict[str, Any] | None,
    te_edges: list[dict[str, Any]],
    mismatch_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    if not graph:
        return {"error": "missing dependency graph"}
    nodes = [n["id"] for n in graph.get("nodes", [])]
    price = graph.get("edges", {}).get("price_coupling", [])
    flow = graph.get("edges", {}).get("physical_flow", [])
    structural = graph.get("edges", {}).get("structural", [])

    price_e = [(e["from"], e["to"], float(e["weight"])) for e in price]
    flow_e = [(e["from"], e["to"], float(e.get("mean_mw", e.get("weight", 0)))) for e in flow]
    te_e = [(e["from"], e["to"], float(e["te"])) for e in te_edges]
    struct_e = [(e["from"], e["to"], 1.0) for e in structural]

    layers = {
        "price": _strength_table(price_e, nodes)[:15],
        "flow": _strength_table(flow_e, nodes)[:15],
        "te": _strength_table(te_e, nodes)[:15],
        "structural": _strength_table(struct_e, nodes)[:15],
    }
    price_comps = _components([(a, b) for a, b, _ in price_e], nodes)
    rank_overlap = _hub_overlap(layers["price"], layers["flow"], layers["te"])
    return {
        "hubs": layers,
        "price_communities": [
            {"size": len(c), "zones": c[:20]} for c in price_comps[:8] if len(c) > 1
        ],
        "hub_overlap": rank_overlap,
        "mismatch_vs_structure": {
            "congested_trade_borders": sum(1 for r in mismatch_rows if r["class"] == "congested_trade"),
            "paper_coupling_borders": sum(1 for r in mismatch_rows if r["class"] == "paper_coupling"),
        },
    }


def _hub_overlap(
    price: list[dict[str, Any]],
    flow: list[dict[str, Any]],
    te: list[dict[str, Any]],
    k: int = 8,
) -> dict[str, Any]:
    p = {r["zone"] for r in price[:k]}
    f = {r["zone"] for r in flow[:k]}
    t = {r["zone"] for r in te[:k]}
    return {
        "top_k": k,
        "price_and_flow": sorted(p & f),
        "price_and_te": sorted(p & t),
        "flow_and_te": sorted(f & t),
        "all_three": sorted(p & f & t),
        "flow_only": sorted(f - p - t),
        "te_only": sorted(t - p - f),
    }


def compute_grid_network(config: AppConfig, graph: dict[str, Any] | None) -> dict[str, Any]:
    buses_dir = config.data_root / "raw" / "static" / "osm_grid"
    bus_files = sorted(buses_dir.glob("buses_*.csv")) if buses_dir.exists() else []
    line_files = sorted(buses_dir.glob("lines_*.csv")) if buses_dir.exists() else []
    link_files = sorted(buses_dir.glob("links_*.csv")) if buses_dir.exists() else []

    substations_by_country: dict[str, int] = defaultdict(int)
    if bus_files:
        with open(bus_files[-1], newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                c = (row.get("country") or "").strip()
                if c:
                    substations_by_country[c] += 1

    voltage_hist: dict[str, int] = defaultdict(int)
    line_count = 0
    if line_files:
        with open(line_files[-1], newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                line_count += 1
                v = (row.get("voltage") or "").split(";")[0].strip()
                if v:
                    voltage_hist[v] += 1

    hvdc = 0
    if link_files:
        with open(link_files[-1], newline="", encoding="utf-8") as fh:
            hvdc = sum(1 for _ in csv.DictReader(fh))

    gem = _load_gem_capacity(config)
    gem_by_country: list[dict[str, Any]] = []
    gem_by_type: list[dict[str, Any]] = []
    if gem is not None:
        country_col = next((c for c in gem.columns if "ountr" in c.lower()), None)
        cap_col = next((c for c in gem.columns if c.strip().lower() == "capacity (mw)"), None)
        type_col = "Type" if "Type" in gem.columns else None
        status_col = "Status" if "Status" in gem.columns else None
        work = gem.copy()
        if status_col:
            work = work[work[status_col].astype(str).str.lower() == "operating"]
        if country_col and cap_col:
            work[cap_col] = pd.to_numeric(work[cap_col], errors="coerce")
            work["iso2"] = work[country_col].map(gem_country_to_iso2)
            cap = work.dropna(subset=["iso2", cap_col]).groupby("iso2")[cap_col].sum()
            gem_by_country = [
                {"country": iso, "capacity_mw": round(float(mw), 1)}
                for iso, mw in cap.sort_values(ascending=False).head(15).items()
            ]
        if type_col and cap_col:
            tcap = work.groupby(type_col)[cap_col].sum().sort_values(ascending=False).head(10)
            gem_by_type = [
                {"type": str(t), "capacity_mw": round(float(mw), 1)} for t, mw in tcap.items()
            ]

    node_grid = []
    if graph:
        for n in graph.get("nodes", []):
            iso = n.get("country") or zone_country(n["id"])
            node_grid.append(
                {
                    "zone": n["id"],
                    "country": iso,
                    "substations": n.get("substation_count") or substations_by_country.get(iso, 0),
                    "lat": n.get("lat"),
                    "lon": n.get("lon"),
                }
            )
        node_grid.sort(key=lambda r: -(r["substations"] or 0))

    top_voltage = sorted(voltage_hist.items(), key=lambda kv: -kv[1])[:8]
    return {
        "osm_lines": line_count,
        "osm_hvdc_links": hvdc,
        "osm_substations": sum(substations_by_country.values()),
        "substations_by_country": [
            {"country": c, "substations": n}
            for c, n in sorted(substations_by_country.items(), key=lambda kv: -kv[1])[:15]
        ],
        "voltage_histogram": [{"voltage_kv": k, "lines": v} for k, v in top_voltage],
        "gem_operating_capacity_by_country": gem_by_country,
        "gem_operating_capacity_by_type": gem_by_type,
        "zones_by_substations": node_grid[:20],
    }


def _year_te_edges_discrete(wide: pd.DataFrame, pairs: list[tuple[str, str]], n_bins: int) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    mask = pd.Series(True, index=wide.index)
    seed = 3
    for a, b in pairs:
        row = _te_on_mask(wide, a, b, mask, min_len=400, n_bins=n_bins, seed=seed)
        seed += 2
        if not row:
            continue
        edges.append({"from": a, "to": b, "te": row["te_a_to_b"]})
        edges.append({"from": b, "to": a, "te": row["te_b_to_a"]})
    return edges


def run_meeting_analyses(
    config: AppConfig,
    year: int,
    *,
    nested_zones: list[str] | None = None,
    n_bins: int = 6,
) -> dict[str, Any]:
    nested_zones = nested_zones or DEFAULT_NESTED_ZONES
    prices_raw = _load_prices(config, year, deseasonalised=False)
    prices_res = _load_prices(config, year, deseasonalised=True)
    flows = _load_flows(config, year)
    wide = _wide_prices(prices_res)
    pairs = [
        (a, b)
        for a, b in _neighbor_undirected(config.zones)
        if a in wide.columns and b in wide.columns
    ]

    te_year = _year_te_edges_discrete(wide, pairs, n_bins=n_bins)
    knn_te = config.data_root / "manifests" / "dashboard" / f"transfer_entropy_{year}.json"
    knn_edges: list[dict[str, Any]] = []
    if knn_te.exists():
        knn_edges = json.loads(knn_te.read_text(encoding="utf-8")).get("edges", [])

    te_for_mismatch = knn_edges or te_year

    mismatch = compute_price_flow_mismatch(prices_raw, flows, te_for_mismatch, pairs)
    regimes = compute_te_regimes(wide, pairs, n_bins=n_bins)
    nested = compute_nested_te(wide, nested_zones, n_bins=n_bins)

    graph_path = config.data_root / "manifests" / f"dependency_graph_{year}.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8")) if graph_path.exists() else None
    structure = compute_dependency_structure(graph, te_for_mismatch, mismatch["borders"])
    grid = compute_grid_network(config, graph)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "year": year,
        "estimator": f"discretized Schreiber TE ({n_bins} quantile bins) for regimes/nested; mismatch TE uses k-NN graph when present",
        "te_regimes": regimes,
        "nested_te": nested,
        "price_flow_mismatch": mismatch,
        "dependency_structure": structure,
        "grid_network": grid,
    }

    out_dir = config.data_root / "manifests" / "dashboard"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = config.data_root / "manifests" / f"meeting_analyses_{year}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["output_path"] = str(out)

    slim = _dashboard_slim(report)
    slim_path = out_dir / f"meeting_analyses_{year}.json"
    slim_path.write_text(json.dumps(slim, indent=2), encoding="utf-8")
    report["dashboard_path"] = str(slim_path)
    return report


def refresh_meeting_dashboard(config: AppConfig, year: int) -> dict[str, Any]:
    """Rebuild the slim dashboard JSON from a saved full meeting_analyses file."""
    full_path = config.data_root / "manifests" / f"meeting_analyses_{year}.json"
    report = json.loads(full_path.read_text(encoding="utf-8"))
    slim = _dashboard_slim(report)
    slim_path = config.data_root / "manifests" / "dashboard" / f"meeting_analyses_{year}.json"
    slim_path.parent.mkdir(parents=True, exist_ok=True)
    slim_path.write_text(json.dumps(slim, indent=2), encoding="utf-8")
    return slim


def _find_border(rows: list[dict[str, Any]], a: str, b: str) -> dict[str, Any] | None:
    want = {a, b}
    for r in rows:
        if {r["a"], r["b"]} == want:
            return r
    return None


def _fmt_r(row: dict[str, Any] | None) -> str:
    if not row or row.get("pearson_r") is None:
        return "—"
    return f"{float(row['pearson_r']):.2f}"


def _fmt_mw(row: dict[str, Any] | None) -> str:
    if not row:
        return "—"
    return f"{float(row['mean_abs_mw']):,.0f}"


def _build_interpretations(report: dict[str, Any]) -> dict[str, Any]:
    mismatch = report["price_flow_mismatch"]
    rows = mismatch.get("borders", [])
    counts = mismatch.get("counts", {})
    fr_es = mismatch.get("fr_es") or _find_border(rows, "FR", "ES")
    es_pt = _find_border(rows, "ES", "PT")
    lt_lv = _find_border(rows, "LT", "LV")
    be_nl = _find_border(rows, "BE", "NL")
    nested = report["nested_te"]
    season_revs = report["te_regimes"].get("season", {}).get("reversals", [])
    season_names = ", ".join(f"{r['a']}–{r['b']}" for r in season_revs[:4]) or "none above the net-TE cutoff"

    n = mismatch.get("n_borders", len(rows))
    ct = counts.get("congested_trade", 0)
    pc = counts.get("paper_coupling", 0)
    al = counts.get("aligned_strong", 0)

    why_mismatch = (
        "Physical MW and wholesale prices answer different questions. Cross-border flow is the energy that "
        "actually moved on the wires (Kirchhoff’s laws, loop flows, and whatever capacity TSOs made available). "
        "Day-ahead Pearson r asks whether the two bidding zones cleared at similar prices every hour. "
        "Those coincide only when the interconnector (or the flow-based domain) is rarely binding. "
        "When the cable is full, power still flows at a high MW rate, but extra cheap generation cannot enter "
        "the expensive zone — so prices decouple. That is congested trade, not a data error."
    )
    why_fr_es = (
        f"France–Spain in 2025: about {_fmt_mw(fr_es)} MW mean |flow| but Pearson r = {_fmt_r(fr_es)} "
        f"(below the 0.85 coupling threshold used for the price graph). The Pyrenees link is a known NTC "
        "bottleneck (ACER still flags FR–ES). Contrast Spain–Portugal on the same Iberian market: "
        f"{_fmt_mw(es_pt)} MW and r = {_fmt_r(es_pt)} — aligned strong. So high flow is not enough for "
        "price integration; the market has to still have spare capacity in the needed direction. "
        "Caveat: ENTSO-E A11 often repeats the same French export total on several FR borders, so FR MW "
        "magnitudes should be read as ‘large’, not as independent meters."
    )
    why_paper = (
        f"{pc} of {n} borders are paper coupling: prices move together while bilateral MW is modest "
        f"(example Lithuania–Latvia, r = {_fmt_r(lt_lv)}, ~{_fmt_mw(lt_lv)} MW). In a coupled market, "
        "a zone pair can share a price because both trade with the same neighbours (Core flow-based, "
        "Baltics, internal Sweden), not because that exact border carries the energy. Pearson r is an "
        "integration statistic; MW is a path statistic."
    )
    why_aligned = (
        f"{al} borders are aligned strong — both a large physical corridor and r ≥ 0.85 "
        f"(examples: ES–PT r = {_fmt_r(es_pt)}; BE–NL r = {_fmt_r(be_nl)}). These are the cases where "
        "the commercial market and the wires are telling the same story."
    )
    why_te_regimes = (
        "A year-average TE arrow is a mixture of many operating regimes. Solar hours, evening peaks, "
        "and hydro seasons do not share a leader. Nested windows (year → month → week → hour) inflate "
        "raw TE as the sample gets shorter and more homogeneous; compare shapes and leader flips, not "
        "absolute bits across scales. Discrete TE on hour-of-day uses lag-1 = yesterday at the same hour."
    )
    why_season = (
        f"Season is the cleanest reversal signal ({len(season_revs)} pairs, including {season_names}). "
        "South-east Europe often switches with winter heating versus autumn hydro/thermal mixes "
        "(e.g. Bulgaria leading Serbia in DJF/MAM, Serbia leading in SON). Weekday vs weekend showed "
        "no leader flips at the 0.03-bit cutoff — the workweek changes level more than direction."
    )
    why_nested = (
        f"On the corridor set {', '.join(nested.get('zones', []))}, "
        f"{nested.get('leader_agreement_year_vs_month_avg')} of {nested.get('pair_count')} pairs keep "
        "the same yearly leader after averaging monthly TE. Where they disagree, a year graph is hiding "
        "a seasonal or hourly reverse. Week-average TE is larger because each week is a short, bursty sample."
    )
    return {
        "mismatch_mechanism": why_mismatch,
        "fr_es": why_fr_es,
        "paper_coupling": why_paper,
        "aligned": why_aligned,
        "te_regimes": why_te_regimes,
        "te_season": why_season,
        "te_nested": why_nested,
        "counts_sentence": (
            f"Of {n} neighbouring borders: {ct} congested trade, {pc} paper coupling, "
            f"{al} aligned strong, {counts.get('informational', 0)} informational-only."
        ),
    }


def _series_from_bins(
    example: dict[str, Any],
    labels: list[str],
) -> dict[str, Any]:
    ab, ba, net = [], [], []
    for lab in labels:
        row = (example.get("bins") or {}).get(lab) or {}
        ab.append(row.get("te_a_to_b"))
        ba.append(row.get("te_b_to_a"))
        net.append(row.get("net_a_minus_b"))
    return {
        "a": example.get("a"),
        "b": example.get("b"),
        "pair": example.get("pair") or f"{example.get('a')}|{example.get('b')}",
        "te_a_to_b": ab,
        "te_b_to_a": ba,
        "net": net,
    }


def _regime_line_charts(regimes: dict[str, Any]) -> dict[str, Any]:
    hod_labels = [f"{h:02d}" for h in range(24)]
    season_labels = ["DJF", "MAM", "JJA", "SON"]
    moy_labels = [f"{m:02d}" for m in range(1, 13)]
    dow_labels = ["weekday", "weekend"]
    spec = {
        "hod": hod_labels,
        "season": season_labels,
        "moy": moy_labels,
        "dow": dow_labels,
    }
    out: dict[str, Any] = {}
    for regime, labels in spec.items():
        examples = (regimes.get(regime) or {}).get("examples") or []
        out[regime] = {
            "labels": labels,
            "series": [_series_from_bins(ex, labels) for ex in examples[:6]],
        }
    return out


def _dashboard_slim(report: dict[str, Any]) -> dict[str, Any]:
    mismatch = report["price_flow_mismatch"]
    regimes = report["te_regimes"]
    nested = report["nested_te"]
    structure = report["dependency_structure"]
    grid = report["grid_network"]
    return {
        "generated_at": report["generated_at"],
        "year": report["year"],
        "estimator": report["estimator"],
        "mismatch": {
            "thresholds": mismatch["thresholds"],
            "counts": mismatch["counts"],
            "n_borders": mismatch["n_borders"],
            "fr_es": mismatch.get("fr_es"),
            "highlights": mismatch["highlights_congested_trade"],
            "borders": mismatch["borders"][:80],
        },
        "te_regimes": {
            regime: {
                "pairs_estimated": payload["pairs_estimated"],
                "reversal_count": payload["reversal_count"],
                "reversals": payload["reversals"][:20],
                "examples": payload["examples"][:6],
            }
            for regime, payload in regimes.items()
        },
        "nested_te": {
            "zones": nested["zones"],
            "weeks_used": nested["weeks_used"],
            "leader_agreement_year_vs_month_avg": nested["leader_agreement_year_vs_month_avg"],
            "pair_count": nested["pair_count"],
            "note": nested["note"],
            "scale_table": nested["scale_table"][:20],
        },
        "structure": {
            "hubs": structure.get("hubs", {}),
            "hub_overlap": structure.get("hub_overlap", {}),
            "price_communities": structure.get("price_communities", []),
            "mismatch_vs_structure": structure.get("mismatch_vs_structure", {}),
        },
        "grid": {
            "osm_lines": grid["osm_lines"],
            "osm_hvdc_links": grid["osm_hvdc_links"],
            "osm_substations": grid["osm_substations"],
            "substations_by_country": grid["substations_by_country"][:12],
            "voltage_histogram": grid["voltage_histogram"],
            "gem_operating_capacity_by_country": grid["gem_operating_capacity_by_country"][:12],
            "gem_operating_capacity_by_type": grid["gem_operating_capacity_by_type"],
            "zones_by_substations": grid["zones_by_substations"][:12],
        },
        "interpretations": _build_interpretations(report),
        "regime_charts": _regime_line_charts(regimes),
        "mismatch_scatter": [
            {
                "a": r["a"],
                "b": r["b"],
                "x": r.get("pearson_r"),
                "y": r.get("mean_abs_mw"),
                "class": r["class"],
            }
            for r in mismatch.get("borders", [])
            if r.get("pearson_r") is not None
        ],
    }
