"""Build formal dependency graph from prices + validated flows + static context."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from energy_collect.config import AppConfig
from energy_collect.flow_validation import run_flow_validation, validated_flow_edges
from energy_collect.utils.zones import border_pairs, zone_codes

ZONE_TO_COUNTRY: dict[str, str] = {
    "DE_LU": "DE",
    "DK_1": "DK",
    "DK_2": "DK",
    "NO_1": "NO",
    "NO_2": "NO",
    "NO_3": "NO",
    "NO_4": "NO",
    "NO_5": "NO",
    "SE_1": "SE",
    "SE_2": "SE",
    "SE_3": "SE",
    "SE_4": "SE",
    "IT_NORTH": "IT",
    "IT_CNOR": "IT",
    "IT_CSUD": "IT",
    "IT_SUD": "IT",
    "IT_SICI": "IT",
    "IT_SARD": "IT",
    "IE_SEM": "IE",
    "GB": "GB",
    "UK": "GB",
}


def zone_country(zone: str) -> str:
    if zone in ZONE_TO_COUNTRY:
        return ZONE_TO_COUNTRY[zone]
    if "_" in zone and not zone.startswith("IT_"):
        return zone.split("_")[0]
    return zone


def _load_prices(config: AppConfig, year: int) -> pd.DataFrame:
    path = config.data_root / "processed" / "entsoe" / f"prices_{year}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Missing {path}")
    df = pd.read_parquet(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def _price_correlation_edges(
    prices: pd.DataFrame,
    *,
    min_r: float | None = 0.85,
) -> list[dict[str, Any]]:
    """All pairwise Pearson r edges; optional |r| filter when min_r is set."""
    pivot = prices.pivot_table(index="timestamp", columns="zone", values="value", aggfunc="mean")
    corr = pivot.corr(min_periods=24 * 30)
    edges: list[dict[str, Any]] = []
    zones = corr.columns.tolist()
    for i, a in enumerate(zones):
        for b in zones[i + 1 :]:
            r = corr.loc[a, b]
            if pd.isna(r):
                continue
            if min_r is not None and abs(r) < min_r:
                continue
            edges.append(
                {
                    "from": a,
                    "to": b,
                    "type": "price_coupling",
                    "weight": round(float(r), 4),
                    "directed": False,
                }
            )
    edges.sort(key=lambda e: -abs(e["weight"]))
    return edges


def _price_edges(prices: pd.DataFrame, *, min_r: float = 0.85) -> list[dict[str, Any]]:
    return _price_correlation_edges(prices, min_r=min_r)


def all_price_coupling_edges(prices: pd.DataFrame, *, threshold_r: float = 0.85) -> list[dict[str, Any]]:
    """Every zone pair with a finite hourly price correlation (for map “all connections”)."""
    edges = _price_correlation_edges(prices, min_r=None)
    for e in edges:
        e["passes_threshold"] = abs(e["weight"]) >= threshold_r
    return edges


def _structural_edges(zones: list[dict]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for pair in border_pairs(zones):
        edges.append(
            {
                "from": pair.from_zone,
                "to": pair.to_zone,
                "type": "structural",
                "weight": 1.0,
                "directed": True,
                "source": "zones.yaml neighbors",
            }
        )
    return edges


def _node_attributes(config: AppConfig) -> dict[str, dict[str, Any]]:
    attrs: dict[str, dict[str, Any]] = {}
    geo_path = config.data_root / "processed" / "static" / "zone_geo.parquet"
    cent_path = config.data_root / "processed" / "static" / "country_centroids.parquet"

    geo = pd.read_parquet(geo_path) if geo_path.exists() else None
    cent = pd.read_parquet(cent_path) if cent_path.exists() else None
    cent_map = (
        cent.set_index("country_iso2").to_dict(orient="index") if cent is not None else {}
    )

    for code in zone_codes(config.zones):
        country = zone_country(code)
        node: dict[str, Any] = {"id": code, "country": country}
        if geo is not None:
            row = geo[geo["zone_code"] == code]
            if not row.empty:
                r = row.iloc[0]
                node["lat"] = round(float(r["centroid_lat"]), 4)
                node["lon"] = round(float(r["centroid_lon"]), 4)
        if country in cent_map:
            node["substation_count"] = int(cent_map[country]["substation_count"])
        attrs[code] = node
    return attrs


def _static_grid_summary(config: AppConfig) -> dict[str, Any]:
    lines = config.data_root / "processed" / "static" / "grid_lines.csv"
    buses = config.data_root / "raw" / "static" / "osm_grid"
    bus_files = list(buses.glob("buses_*.csv")) if buses.exists() else []
    summary: dict[str, Any] = {"source": "PyPSA-Eur OSM (Zenodo)", "merged": False}
    if lines.exists():
        df = pd.read_csv(lines, nrows=0)
        summary["grid_lines_file"] = str(lines)
        summary["line_columns"] = list(df.columns)
        summary["merged"] = True
    if bus_files:
        summary["buses_file"] = str(sorted(bus_files)[-1])
    gem_dir = config.data_root / "raw" / "static" / "gem"
    gem_files = list(gem_dir.glob("*.xlsx")) + list(gem_dir.glob("*.csv")) if gem_dir.exists() else []
    summary["gem_available"] = bool(gem_files)
    if gem_files:
        summary["gem_file"] = str(gem_files[-1])
    return summary


def build_dependency_graph(
    config: AppConfig,
    year: int,
    *,
    price_min_r: float = 0.85,
    flow_validation: dict[str, Any] | None = None,
    include_structural: bool = True,
) -> dict[str, Any]:
    if flow_validation is None:
        flow_validation = run_flow_validation(config, year)

    prices = _load_prices(config, year)
    nodes = _node_attributes(config)
    price_edges = _price_edges(prices, min_r=price_min_r)
    flow_edges = [
        {
            "from": e["from"],
            "to": e["to"],
            "type": e.get("edge_type", "physical_flow"),
            "weight": e["mw"],
            "mean_mw": e["mean_mw"],
            "directed": True,
            "validated": True,
            "validation_status": e.get("validation_status"),
            "direction_note": e.get("direction_note"),
        }
        for e in validated_flow_edges(flow_validation)
    ]
    structural = _structural_edges(config.zones) if include_structural else []

    graph = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "year": year,
        "nodes": list(nodes.values()),
        "edges": {
            "price_coupling": price_edges,
            "physical_flow": flow_edges,
            "structural": structural,
        },
        "stats": {
            "nodes": len(nodes),
            "price_edges": len(price_edges),
            "flow_edges_validated": len(flow_edges),
            "structural_edges": len(structural),
            "flow_pairs_ok": flow_validation["by_status"].get("ok", 0),
            "flow_pairs_duplicate": flow_validation["by_status"].get("duplicate_export", 0),
        },
        "flow_validation_ref": flow_validation.get("output_path"),
        "static_layers": _static_grid_summary(config),
    }
    return graph


def write_dependency_graph(config: AppConfig, year: int, **kwargs: Any) -> Path:
    graph = build_dependency_graph(config, year, **kwargs)
    out = config.data_root / "manifests" / f"dependency_graph_{year}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(graph, indent=2), encoding="utf-8")
    return out
