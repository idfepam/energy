#!/usr/bin/env python3
"""Build Leaflet map data + standalone HTML for Europe dependency visualization."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT_JSON = ROOT / "data/manifests/map_leaflet.json"
OUT_HTML = ROOT / "docs/europe_dependency_map.html"

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

# Legacy fallback when flow_validation JSON not yet built
FR_KEEP = {("FR", "BE"), ("FR", "ES"), ("FR", "CH")}

FLOW_VALIDATION = ROOT / "data/manifests/flow_validation_2025.json"


def zone_country(zone: str) -> str:
    if zone in ZONE_TO_COUNTRY:
        return ZONE_TO_COUNTRY[zone]
    if "_" in zone and not zone.startswith("IT_"):
        return zone.split("_")[0]
    return zone


def zone_pos(zone: str, centroids: pd.DataFrame) -> tuple[float, float] | None:
    country = zone_country(zone)
    row = centroids[centroids["country_iso2"] == country]
    if row.empty:
        return None
    r = row.iloc[0]
    return float(r["centroid_lat"]), float(r["centroid_lon"])


def build_map_data() -> dict:
    centroids = pd.read_parquet(ROOT / "data/processed/static/country_centroids.parquet")
    countries = [
        {
            "iso": row.country_iso2,
            "lat": round(float(row.centroid_lat), 4),
            "lon": round(float(row.centroid_lon), 4),
            "n": int(row.substation_count),
        }
        for row in centroids.itertuples()
    ]

    prices = pd.read_parquet(ROOT / "data/processed/entsoe/prices_2025.parquet")
    wide = prices.pivot_table(index="timestamp", columns="zone", values="value", aggfunc="mean")
    corr = wide.corr(min_periods=24 * 30)

    flows = pd.read_parquet(ROOT / "data/processed/entsoe/flows_2025.parquet")
    flow_mean = (
        flows.groupby(["from_zone", "to_zone"])["value"]
        .mean()
        .reset_index()
        .sort_values("value", ascending=False)
    )

    flow_lines: list[dict] = []
    if FLOW_VALIDATION.exists():
        val = json.loads(FLOW_VALIDATION.read_text(encoding="utf-8"))
        flow_candidates = [
            (p["from"], p["to"], p["mw"])
            for p in val.get("graph_flow_edges", val.get("validated_pairs", []))
        ]
        flow_candidates.sort(key=lambda x: -x[2])
    else:
        flow_candidates = [
            (row.from_zone, row.to_zone, abs(float(row.value)))
            for row in flow_mean.itertuples()
            if not (row.from_zone == "FR" and (row.from_zone, row.to_zone) not in FR_KEEP)
        ]

    for fz, tz, mw in flow_candidates:
        pos_a = zone_pos(fz, centroids)
        pos_b = zone_pos(tz, centroids)
        if not pos_a or not pos_b:
            continue
        lat1, lon1 = pos_a
        lat2, lon2 = pos_b
        if math.hypot(lat2 - lat1, lon2 - lon1) < 0.25:
            continue
        flow_lines.append(
            {
                "from": fz,
                "to": tz,
                "mw": round(mw),
                "lat1": round(lat1, 4),
                "lon1": round(lon1, 4),
                "lat2": round(lat2, 4),
                "lon2": round(lon2, 4),
            }
        )
        if len(flow_lines) >= 12:
            break

    price_lines: list[dict] = []
    for i in corr.columns:
        for j in corr.columns:
            if i >= j:
                continue
            r = corr.loc[i, j]
            if pd.isna(r) or r < 0.92:
                continue
            pos_a = zone_pos(i, centroids)
            pos_b = zone_pos(j, centroids)
            if not pos_a or not pos_b:
                continue
            lat1, lon1 = pos_a
            lat2, lon2 = pos_b
            if math.hypot(lat2 - lat1, lon2 - lon1) < 0.12:
                continue
            price_lines.append(
                {
                    "from": i,
                    "to": j,
                    "r": round(float(r), 3),
                    "lat1": round(lat1, 4),
                    "lon1": round(lon1, 4),
                    "lat2": round(lat2, 4),
                    "lon2": round(lon2, 4),
                }
            )
    price_lines.sort(key=lambda x: -x["r"])

    return {
        "countries": countries,
        "flow_lines": flow_lines,
        "price_lines": price_lines[:18],
    }


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Europe electricity dependency map</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <style>
    html, body, #map { margin: 0; height: 100%; width: 100%; background: #eef1f4; }
    .legend {
      background: rgba(255,255,255,0.94);
      color: #333;
      padding: 10px 12px;
      border-radius: 6px;
      font: 11px/1.4 system-ui, sans-serif;
      border: 1px solid #ccc;
      box-shadow: none;
    }
    .legend h4 { margin: 0 0 6px; font-size: 11px; font-weight: 600; color: #111; }
    .legend div { margin: 3px 0; display: flex; align-items: center; gap: 8px; }
    .swatch-line { width: 22px; height: 0; border-top: 3px solid #5b9bd5; }
    .swatch-dash { width: 22px; height: 0; border-top: 2px dashed #888; }
    .swatch-dot { width: 10px; height: 10px; border-radius: 50%; background: #5b9bd5; opacity: 0.7; }
    .leaflet-container { background: #eef1f4; font-family: system-ui, sans-serif; }
  </style>
</head>
<body>
  <div id="map"></div>
  <script>
    const DATA = __DATA__;

    const map = L.map('map', { zoomControl: true, attributionControl: true }).setView([54, 15], 4);
    L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
      maxZoom: 20,
      subdomains: 'abcd',
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
    }).addTo(map);

    const maxN = Math.max(...DATA.countries.map(c => c.n));
    const maxMw = Math.max(...DATA.flow_lines.map(f => f.mw));

    DATA.price_lines.forEach(e => {
      L.polyline([[e.lat1, e.lon1], [e.lat2, e.lon2]], {
        color: '#888',
        weight: 1 + (e.r - 0.92) * 6,
        opacity: 0.45 + (e.r - 0.92) * 1.5,
        dashArray: '6 5',
      }).bindTooltip(`${e.from} – ${e.to}: r=${e.r}`, { sticky: true }).addTo(map);
    });

    DATA.flow_lines.forEach(e => {
      const w = 2 + (e.mw / maxMw) * 6;
      const line = L.polyline([[e.lat1, e.lon1], [e.lat2, e.lon2]], {
        color: '#5b9bd5',
        weight: w,
        opacity: 0.65,
      }).bindTooltip(`${e.from} → ${e.to}: ${e.mw.toLocaleString()} MW (mean hourly)`, { sticky: true });
      line.addTo(map);
      const mid = L.latLng((e.lat1 + e.lat2) / 2, (e.lon1 + e.lon2) / 2);
      L.marker(mid, {
        icon: L.divIcon({
          className: '',
          html: '<div style="color:#5b9bd5;font-size:14px;font-weight:700;text-shadow:0 0 3px #000">›</div>',
          iconSize: [12, 12],
          iconAnchor: [4, 8],
        }),
        interactive: false,
      }).addTo(map);
    });

    DATA.countries.forEach(c => {
      const r = 4 + (c.n / maxN) * 14;
      L.circleMarker([c.lat, c.lon], {
        radius: r,
        color: '#5b9bd5',
        weight: 1.2,
        fillColor: '#5b9bd5',
        fillOpacity: 0.35,
      }).bindTooltip(`${c.iso}: ${c.n} OSM substations`, { sticky: true }).addTo(map);
      L.marker([c.lat, c.lon], {
        icon: L.divIcon({
          className: '',
          html: `<div style="transform:translate(-50%,-130%);font:600 10px system-ui;color:#222;text-shadow:0 0 3px #fff">${c.iso}</div>`,
          iconSize: [0, 0],
        }),
        interactive: false,
      }).addTo(map);
    });

    const legend = L.control({ position: 'topleft' });
    legend.onAdd = () => {
      const div = L.DomUtil.create('div', 'legend');
      div.innerHTML = `
        <h4>ENTSO-E 2025 · Carto basemap</h4>
        <div><span class="swatch-line"></span> Physical flow (top borders, MW)</div>
        <div><span class="swatch-dash"></span> Price coupling (r ≥ 0.92)</div>
        <div><span class="swatch-dot"></span> Substation density (PyPSA-Eur OSM)</div>`;
      return div;
    };
    legend.addTo(map);

    map.fitBounds(L.latLngBounds(DATA.countries.map(c => [c.lat, c.lon])).pad(0.08));
  </script>
</body>
</html>
"""


def write_html(data: dict) -> None:
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    html = HTML_TEMPLATE.replace("__DATA__", json.dumps(data, separators=(",", ":")))
    OUT_HTML.write_text(html, encoding="utf-8")
    srcdoc_path = ROOT / "data/manifests/canvas_map_srcdoc.txt"
    srcdoc_path.write_text(
        html.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${"),
        encoding="utf-8",
    )


def main() -> None:
    data = build_map_data()
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(data, indent=2), encoding="utf-8")
    write_html(data)
    print(f"Wrote {OUT_JSON} ({len(data['countries'])} countries, {len(data['flow_lines'])} flows)")
    print(f"Wrote {OUT_HTML}")


if __name__ == "__main__":
    main()
