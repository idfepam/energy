#!/usr/bin/env python3
"""Build geographic reference tables: zones, countries, centroids."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml
from entsoe._mappings import AREA_CODES, COUNTRY_NAMES, EIC_TO_ISO

ROOT = Path(__file__).resolve().parents[1]


# Map bidding-zone codes to ISO2 country for centroid lookup (OSM uses ISO2)
ZONE_TO_COUNTRY: dict[str, str] = {
    "DE_LU": "DE",
    "DE_AT_LU": "DE",
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


def build_zone_reference(zones_cfg: list[dict]) -> pd.DataFrame:
    rows = []
    for z in zones_cfg:
        code = z["code"]
        country = zone_country(code)
        eic = AREA_CODES.get(code) or EIC_TO_ISO.get(code, "")
        rows.append(
            {
                "zone_code": code,
                "zone_name": z.get("name") or COUNTRY_NAMES.get(code, code),
                "country_iso2": country,
                "country_name": COUNTRY_NAMES.get(country, country),
                "eic_code": eic,
                "neighbors": ",".join(z.get("neighbors", [])),
                "is_subnational": code != country and "_" in code,
            }
        )
    return pd.DataFrame(rows)


def build_country_centroids(buses_csv: Path) -> pd.DataFrame:
    buses = pd.read_csv(buses_csv, usecols=["country", "x", "y", "voltage"])
    buses = buses[buses["country"].notna()]
    cent = (
        buses.groupby("country")
        .agg(
            centroid_lon=("x", "mean"),
            centroid_lat=("y", "mean"),
            substation_count=("x", "count"),
            max_voltage_kv=("voltage", "max"),
        )
        .reset_index()
        .rename(columns={"country": "country_iso2"})
    )
    return cent


def attach_zone_centroids(zones: pd.DataFrame, centroids: pd.DataFrame) -> pd.DataFrame:
    merged = zones.merge(centroids, on="country_iso2", how="left")
    return merged


def main() -> None:
    out_dir = ROOT / "data" / "processed" / "static"
    out_dir.mkdir(parents=True, exist_ok=True)

    zones_cfg = yaml.safe_load((ROOT / "config" / "zones.yaml").read_text())["zones"]
    zones_df = build_zone_reference(zones_cfg)

    buses_path = ROOT / "data" / "raw" / "static" / "osm_grid" / "buses_20260820.csv"
    if buses_path.exists():
        centroids = build_country_centroids(buses_path)
        centroids.to_parquet(out_dir / "country_centroids.parquet", index=False)
        zones_geo = attach_zone_centroids(zones_df, centroids)
    else:
        centroids = pd.DataFrame()
        zones_geo = zones_df

    zones_df.to_parquet(out_dir / "zone_reference.parquet", index=False)
    zones_geo.to_parquet(out_dir / "zone_geo.parquet", index=False)

    meta = {
        "zone_count": len(zones_df),
        "countries_with_centroids": len(centroids),
        "sources": {
            "zones": "config/zones.yaml + entsoe._mappings",
            "centroids": "PyPSA-Eur OSM buses (mean substation coordinates per country)",
        },
    }
    (out_dir / "geo_manifest.json").write_text(json.dumps(meta, indent=2))
    print(f"Wrote zone_reference ({len(zones_df)} zones)")
    print(f"Wrote country_centroids ({len(centroids)} countries)")
    print(f"Wrote zone_geo ({zones_geo['centroid_lat'].notna().sum()} zones with coordinates)")


if __name__ == "__main__":
    main()
