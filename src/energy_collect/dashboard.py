"""Assemble dashboard JSON bundle for the web frontend."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from energy_collect.config import AppConfig
from energy_collect.graph import all_price_coupling_edges
from energy_collect.map_layers import build_map_layers
from energy_collect.seasonality import run_seasonality_decomposition, CHART_ZONES
from energy_collect.transfer_entropy import compute_te_edges, run_transfer_entropy
from energy_collect.utils.zones import border_pairs
from energy_collect.meeting_analyses import run_meeting_analyses

DATASET_LABELS = {
    "day_ahead_prices": "Day-ahead prices",
    "actual_load": "Actual load",
    "generation_actual": "Generation (actual)",
    "imbalance_prices": "Imbalance prices",
    "crossborder_flows": "Cross-border flows",
}

DATASET_DOCS = {
    "day_ahead_prices": "ENTSO-E A44 (12.1.D) — day-ahead price, EUR/MWh",
    "actual_load": "ENTSO-E A65 (6.1.A) — total consumption, MW",
    "generation_actual": "ENTSO-E A75 (16.1.B&C) — generation by fuel, MW",
    "imbalance_prices": "ENTSO-E A85 (17.1.G) — balancing price, EUR/MWh",
    "crossborder_flows": "ENTSO-E A11 (12.1.G) — physical border flow, MW",
}


def _zone_names(zones_config: list[dict]) -> dict[str, str]:
    return {z["code"]: z["name"] for z in zones_config}

def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _border_te_edges(te_edges: list[dict[str, Any]], zones_config: list[dict]) -> list[dict[str, Any]]:
    allowed = {(p.from_zone, p.to_zone) for p in border_pairs(zones_config)}
    filtered = [e for e in te_edges if (e["from"], e["to"]) in allowed]
    filtered.sort(key=lambda e: -e["te"])
    return filtered


def _load_border_te_all(
    config: AppConfig,
    year: int,
    te: dict[str, Any],
    *,
    min_te: float,
) -> list[dict[str, Any]]:
    cached = te.get("border_edges_all")
    if cached:
        return cached

    path = config.data_root / "processed" / "entsoe" / f"prices_deseasonalised_{year}.parquet"
    if not path.exists():
        run_seasonality_decomposition(config, year, dataset="prices")
    prices = pd.read_parquet(path)
    prices["timestamp"] = pd.to_datetime(prices["timestamp"], utc=True)

    meta = te if te.get("estimator") else {}
    border_edges_all = compute_te_edges(
        prices,
        min_te=0.0,
        method=meta.get("estimator", "knn"),
        k=int(meta.get("k_neighbors", 4)),
        alpha=float(meta.get("alpha", 1.0)),
        r=int(meta.get("memory_r", 1)),
        l=int(meta.get("memory_l", 1)),
        effective=bool(meta.get("effective_rte", True)),
        neighbor_only=True,
        zones_config=config.zones,
    )
    for e in border_edges_all:
        e["passes_threshold"] = e["te"] >= min_te
    return border_edges_all


def build_dashboard_bundle(config: AppConfig, year: int) -> dict[str, Any]:
    seasonality = _load_json(config.data_root / "manifests" / "dashboard" / f"seasonality_prices_{year}.json")
    if seasonality is None:
        seasonality = run_seasonality_decomposition(config, year, dataset="prices")

    load_seasonality = _load_json(config.data_root / "manifests" / "dashboard" / f"seasonality_load_{year}.json")
    if load_seasonality is None:
        load_path = config.data_root / "processed" / "entsoe" / f"load_{year}.parquet"
        if load_path.exists():
            load_seasonality = run_seasonality_decomposition(config, year, dataset="load")

    te = _load_json(config.data_root / "manifests" / "dashboard" / f"transfer_entropy_{year}.json")
    if te is None:
        te = run_transfer_entropy(config, year, use_deseasonalised=True, neighbor_only=False)

    graph = _load_json(config.data_root / "manifests" / f"dependency_graph_{year}.json")
    gaps = _load_json(config.data_root / "manifests" / "gaps_report.json")
    map_data = _load_json(config.data_root / "manifests" / "map_leaflet.json")
    meeting = _load_json(config.data_root / "manifests" / "dashboard" / f"meeting_analyses_{year}.json")
    if meeting is None:
        meeting_full = run_meeting_analyses(config, year)
        meeting = _load_json(Path(meeting_full["dashboard_path"]))

    target_zones = len(config.zones)
    min_te = float(te.get("min_te", 0.003))
    all_te = te.get("edges", [])
    border_te = _border_te_edges(all_te, config.zones)
    border_te_all = _load_border_te_all(config, year, te, min_te=min_te)

    prices_path = config.data_root / "processed" / "entsoe" / f"prices_{year}.parquet"
    prices_for_corr = pd.read_parquet(prices_path)
    prices_for_corr["timestamp"] = pd.to_datetime(prices_for_corr["timestamp"], utc=True)
    price_min_r = 0.85
    price_edges_all = all_price_coupling_edges(prices_for_corr, threshold_r=price_min_r)

    map_layers = build_map_layers(
        graph,
        border_te_all,
        price_edges_all=price_edges_all,
        zones_config=config.zones,
        price_min_r=price_min_r,
        price_strongest_floor=0.80,
        te_min=min_te,
    )

    coverage_rows: list[dict[str, str | int]] = []
    if gaps and gaps.get("full_year_gaps"):
        for ds, scopes in gaps["full_year_gaps"].items():
            missing_n = len(scopes)
            coverage_rows.append(
                {
                    "dataset": ds,
                    "label": DATASET_LABELS.get(ds, ds.replace("_", " ").title()),
                    "doc": DATASET_DOCS.get(ds, ""),
                    "missing": ", ".join(scopes) if scopes else "—",
                    "present": target_zones - missing_n,
                }
            )

    prices = pd.read_parquet(prices_path)
    prices["timestamp"] = pd.to_datetime(prices["timestamp"], utc=True)
    year_prices = prices[prices["timestamp"].dt.year == year]

    monthly = (
        year_prices.assign(month=year_prices["timestamp"].dt.strftime("%Y-%m"))
        .groupby(["month", "zone"])["value"]
        .mean()
        .reset_index()
    )
    monthly_chart: dict[str, list[dict[str, float | str]]] = {}
    price_summaries: list[dict[str, float | str | int]] = []
    for z in CHART_ZONES:
        sub = monthly[monthly["zone"] == z].sort_values("month")
        monthly_chart[z] = [{"month": r.month, "price": round(float(r.value), 1)} for r in sub.itertuples()]
        zdata = year_prices[year_prices["zone"] == z]["value"]
        if len(zdata):
            price_summaries.append(
                {
                    "zone": z,
                    "mean": round(float(zdata.mean()), 1),
                    "min": round(float(zdata.min()), 1),
                    "max": round(float(zdata.max()), 1),
                    "hours": int(zdata.count()),
                }
            )

    zones_with_prices = int(year_prices["zone"].nunique())

    bundle = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "year": year,
        "target_zones": target_zones,
        "zones_with_prices": zones_with_prices,
        "map": map_data,
        "map_layers": map_layers,
        "graph_stats": graph.get("stats") if graph else {},
        "price_edges_count": len((graph or {}).get("edges", {}).get("price_coupling", [])),
        "flow_edges_count": len((graph or {}).get("edges", {}).get("physical_flow", [])),
        "te_edge_count": te.get("edge_count", 0),
        "te_border_count": len(border_te),
        "te_top_value": border_te[0]["te"] if border_te else 0,
        "te_border_edges": border_te[:25],
        "te_edges": te.get("top_edges", all_te)[:30],
        "te_method": te.get("method", ""),
        "te_reference": te.get("reference", ""),
        "sources_meta": {
            "te_method": te.get("method", ""),
            "te_min": min_te,
            "te_reference": te.get("reference", ""),
            "seasonality_method": seasonality.get("method", ""),
            "load_seasonality_zones": (load_seasonality or {}).get("zones", 0),
            "static_layers": (graph or {}).get("static_layers", {}),
        },
        "seasonality": {
            "zones": seasonality.get("zones", 0),
            "unit": seasonality.get("unit", "EUR/MWh"),
            "method": seasonality.get("method", ""),
            "top_hod_strength": seasonality.get("zone_summaries", [])[:10],
            "top_moy_strength": seasonality.get("top_moy_strength", [])[:10],
            "hourly_profiles": {
                k: seasonality["hourly_profiles"][k]
                for k in CHART_ZONES
                if k in seasonality.get("hourly_profiles", {})
            },
            "monthly_profiles": seasonality.get("monthly_profiles", {}),
            "quarterly_profiles": seasonality.get("quarterly_profiles", {}),
            "quarter_labels": seasonality.get("quarter_labels", []),
            "calendar_month_labels": seasonality.get("calendar_month_labels", []),
        },
        "load_seasonality": {
            "zones": load_seasonality.get("zones", 0) if load_seasonality else 0,
            "unit": load_seasonality.get("unit", "MW") if load_seasonality else "MW",
            "top_moy_strength": (load_seasonality or {}).get("top_moy_strength", [])[:5],
            "quarterly_profiles": (load_seasonality or {}).get("quarterly_profiles", {}),
            "quarter_labels": (load_seasonality or {}).get("quarter_labels", []),
        },
        "monthly_prices": monthly_chart,
        "price_summaries": price_summaries,
        "coverage_gaps": coverage_rows,
        "zone_names": _zone_names(config.zones),
        "meeting": meeting or {},
    }

    dash_dir = Path(__file__).resolve().parents[2] / "docs" / "dashboard"
    dash_dir.mkdir(parents=True, exist_ok=True)

    json_path = dash_dir / "data.json"
    json_path.write_text(json.dumps(bundle, indent=2), encoding="utf-8")

    js_path = dash_dir / "data.js"
    js_path.write_text(f"window.DASHBOARD_DATA = {json.dumps(bundle)};\n", encoding="utf-8")

    bundle["output_json"] = str(json_path)
    bundle["output_js"] = str(js_path)
    return bundle
