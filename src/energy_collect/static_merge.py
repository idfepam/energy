"""Merge PyPSA-Eur / GEM static layers onto dependency graph nodes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from energy_collect.config import AppConfig
from energy_collect.graph import zone_country
from energy_collect.utils.gem_countries import gem_country_to_iso2


def _load_gem_capacity(config: AppConfig) -> pd.DataFrame | None:
    gem_dir = config.data_root / "raw" / "static" / "gem"
    if not gem_dir.exists():
        return None
    files = sorted(gem_dir.glob("*.csv")) + sorted(gem_dir.glob("*.parquet"))
    if not files:
        return None
    path = files[-1]
    if path.suffix == ".csv":
        df = pd.read_csv(path, low_memory=False)
    else:
        df = pd.read_parquet(path)
    return df


def merge_static_layers(config: AppConfig, year: int) -> dict[str, Any]:
    graph_path = config.data_root / "manifests" / f"dependency_graph_{year}.json"
    if not graph_path.exists():
        raise FileNotFoundError(
            f"Missing {graph_path}. Run: energy-collect build-graph --year {year}"
        )

    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    lines_path = config.data_root / "processed" / "static" / "grid_lines.csv"
    grid_line_count = 0
    if lines_path.exists():
        grid_line_count = sum(1 for _ in open(lines_path, encoding="utf-8")) - 1

    gem = _load_gem_capacity(config)
    capacity_by_country: dict[str, float] = {}
    if gem is not None:
        country_col = next(
            (c for c in gem.columns if c.lower().replace(" ", "") in ("country/area", "country")),
            None,
        )
        cap_col = next(
            (c for c in gem.columns if c.strip().lower() == "capacity (mw)"),
            next((c for c in gem.columns if "capacity" in c.lower() and "mw" in c.lower()), None),
        )
        if country_col and cap_col:
            tmp = gem.copy()
            tmp[cap_col] = pd.to_numeric(tmp[cap_col], errors="coerce")
            tmp["iso2"] = tmp[country_col].map(gem_country_to_iso2)
            tmp = tmp.dropna(subset=["iso2", cap_col])
            for iso2, grp in tmp.groupby("iso2"):
                capacity_by_country[str(iso2)] = float(grp[cap_col].sum())

    for node in graph["nodes"]:
        country = node.get("country") or zone_country(node["id"])
        node["static"] = {
            "osm_grid_lines_europe": grid_line_count,
            "gem_capacity_mw": round(capacity_by_country.get(country, 0.0), 1),
        }

    graph["static_layers"] = {
        **graph.get("static_layers", {}),
        "merged_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "grid_lines_count": grid_line_count,
        "gem_available": gem is not None and bool(capacity_by_country),
        "gem_countries_with_capacity": len(capacity_by_country),
        "citation_osm": "PyPSA-Eur OSM grid (Zenodo) — ODbL 1.0",
        "citation_gem": "Global Energy Monitor GIPT — attribute on reuse",
    }

    out = config.data_root / "manifests" / f"dependency_graph_{year}_with_static.json"
    out.write_text(json.dumps(graph, indent=2), encoding="utf-8")
    return {"output_path": str(out), "grid_lines": grid_line_count, "gem_countries": len(capacity_by_country)}
