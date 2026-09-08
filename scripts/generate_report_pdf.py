#!/usr/bin/env python3
"""Generate static Europe map PNG + ENTSO-E 2025 PDF report."""

from __future__ import annotations

import base64
import json
import urllib.request
from datetime import date
from pathlib import Path

import contextily as cx
import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd
import yaml
from fpdf import FPDF
from fpdf.enums import XPos, YPos
from matplotlib.lines import Line2D
from PIL import Image
from pyproj import Transformer
from shapely.geometry import LineString

ROOT = Path(__file__).resolve().parents[1]
MAP_JSON = ROOT / "data/manifests/map_leaflet.json"
ASSETS = ROOT / "docs/report_assets"
PDF_OUT = ROOT / "docs/entsoe_2025_report.pdf"
B64_OUT = ROOT / "data/manifests/map_png_base64.txt"
FLOW_VALIDATION = ROOT / "data/manifests/flow_validation_2025.json"
GRAPH_STATIC = ROOT / "data/manifests/dependency_graph_2025_with_static.json"
GEM_PARQUET = ROOT / "data/raw/static/gem/plants_eu_20260822.parquet"
CANVAS_PATH = Path(
    "/Users/purple/.cursor/projects/Users-purple-Desktop-Research-energy/canvases/entsoe-2025-overview.canvas.tsx"
)

GEM_COUNTRY_TO_ISO2 = {
    "Germany": "DE", "France": "FR", "Spain": "ES", "United Kingdom": "GB",
    "Italy": "IT", "Poland": "PL", "Netherlands": "NL", "Sweden": "SE",
    "Norway": "NO", "Finland": "FI", "Belgium": "BE", "Austria": "AT",
    "Portugal": "PT", "Greece": "GR", "Romania": "RO", "Czech Republic": "CZ",
    "Hungary": "HU", "Denmark": "DK", "Ireland": "IE", "Slovakia": "SK",
    "Bulgaria": "BG", "Croatia": "HR", "Slovenia": "SI", "Lithuania": "LT",
    "Latvia": "LV", "Estonia": "EE", "Luxembourg": "LU", "Switzerland": "CH",
    "Serbia": "RS", "Bosnia and Herzegovina": "BA", "Montenegro": "ME",
    "North Macedonia": "MK", "Albania": "AL",
}
NE_PATH = ROOT / "data/raw/static/naturalearth/ne_50m_admin_0_countries.geojson"
NE_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
    "geojson/ne_50m_admin_0_countries.geojson"
)
# OSM volunteer tile servers block bulk/script requests (403). Use Carto instead.
CARTO_LIGHT = cx.providers.CartoDB.Positron

TO_3857 = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
EUROPE_BBOX = (-12.0, 34.0, 35.0, 72.0)  # lon min, lat min, lon max, lat max
EUROPE_ISO3 = {
    "ALB", "AND", "AUT", "BLR", "BEL", "BIH", "BGR", "HRV", "CZE", "DNK", "EST", "FIN", "FRA",
    "DEU", "GRC", "HUN", "ISL", "IRL", "ITA", "XKX", "LVA", "LTU", "LUX", "MKD", "MLT", "MDA",
    "MCO", "MNE", "NLD", "NOR", "POL", "PRT", "ROU", "SRB", "SVK", "SVN", "ESP", "SWE", "CHE",
    "UKR", "GBR",
}

ZONE_TO_COUNTRY: dict[str, str] = {
    "DE_LU": "DE", "DK_1": "DK", "DK_2": "DK",
    "NO_1": "NO", "NO_2": "NO", "NO_3": "NO", "NO_4": "NO", "NO_5": "NO",
    "SE_1": "SE", "SE_2": "SE", "SE_3": "SE", "SE_4": "SE",
    "IT_NORTH": "IT", "IT_CNOR": "IT", "IT_CSUD": "IT", "IT_SUD": "IT", "IT_SICI": "IT", "IT_SARD": "IT",
    "IE_SEM": "IE", "GB": "GB", "UK": "GB",
}

DATASET_ROWS: list[tuple[str, str, str, str, str]] = [
    ("day_ahead_prices", "A44 / 12.1.D", "EUR/MWh", "Hourly market clearing price for next-day delivery", "43 zones"),
    ("actual_load", "A65 / 6.1.A", "MW", "Total electricity demand in the zone", "44 zones"),
    ("generation_actual", "A75 / 16.1.B&C", "MW", "Hourly output split by fuel type (PSR)", "41 zones"),
    ("imbalance_prices", "A85 / 17.1.G", "EUR/MWh", "Balancing energy price (system stress)", "40 zones"),
    ("crossborder_flows", "A11 / 12.1.G", "MW", "Physical power flow between two zones", "171 pairs"),
    ("scheduled_exchanges", "A09 / 12.1.E", "MW", "Commercially scheduled cross-border trade", "171 pairs"),
    ("net_transfer_capacity", "A61 / 11.1", "MW", "Day-ahead max transferable capacity (NTC)", "Partial"),
]

COLUMN_ROWS: list[tuple[str, str, str, str]] = [
    ("timestamp", "All", "UTC datetime", "Start of measurement interval"),
    ("value", "All", "float", "Main numeric value (see unit per dataset)"),
    ("zone", "Zone-level", "string", "Bidding zone code (e.g. DE_LU, FR, IT_NORTH)"),
    ("from_zone / to_zone", "Border pairs", "string", "Directed flow: power exported from -> imported to"),
    ("psr_type", "Generation", "string", "Fuel type: Nuclear, Solar, Wind Onshore, Fossil Gas, ..."),
    ("currency", "Prices", "string", "EUR"),
    ("price_unit", "Prices", "string", "MWH (= EUR per MWh)"),
    ("quantity_unit", "Load/flows", "string", "MW (megawatts)"),
]

PSR_ROWS: list[tuple[str, str, str]] = [
    ("B14", "Nuclear", "Low-carbon baseload"),
    ("B16", "Solar", "Renewable"),
    ("B19", "Wind Onshore", "Renewable"),
    ("B18", "Wind Offshore", "Renewable"),
    ("B04", "Fossil Gas", "Fossil"),
    ("B05", "Fossil Hard coal", "Fossil"),
    ("B02", "Fossil Brown coal/Lignite", "Fossil"),
    ("B11", "Hydro Run-of-river", "Renewable"),
    ("B12", "Hydro Water Reservoir", "Renewable"),
    ("B10", "Hydro Pumped Storage", "Storage"),
    ("B01", "Biomass", "Renewable"),
    ("B09", "Geothermal", "Renewable"),
]


def zone_country(zone: str) -> str:
    if zone in ZONE_TO_COUNTRY:
        return ZONE_TO_COUNTRY[zone]
    if "_" in zone and not zone.startswith("IT_"):
        return zone.split("_")[0]
    return zone


def load_zone_rows() -> list[list[str]]:
    cfg = yaml.safe_load((ROOT / "config/zones.yaml").read_text(encoding="utf-8"))
    rows: list[list[str]] = []
    for z in sorted(cfg["zones"], key=lambda x: x["code"]):
        code = z["code"]
        country = zone_country(code)
        sub = "Yes" if (code != country and "_" in code) else "No"
        rows.append([code, z["name"], country, sub])
    return rows


def _ensure_map_data() -> dict:
    if not MAP_JSON.exists():
        from build_canvas_map import build_map_data, write_html

        data = build_map_data()
        MAP_JSON.parent.mkdir(parents=True, exist_ok=True)
        MAP_JSON.write_text(json.dumps(data, indent=2), encoding="utf-8")
        write_html(data)
    return json.loads(MAP_JSON.read_text(encoding="utf-8"))


def _ensure_naturalearth() -> Path:
    if not NE_PATH.exists():
        NE_PATH.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(NE_URL, NE_PATH)
    return NE_PATH


def _add_basemap(ax) -> str:
    """Carto Positron tiles (OSM-based, script-friendly). Natural Earth if offline."""
    try:
        cx.add_basemap(ax, source=CARTO_LIGHT, zoom=5, attribution=False)
        return "Carto Positron basemap (OpenStreetMap data)"
    except Exception:
        pass
    gdf = gpd.read_file(_ensure_naturalearth())
    europe = gdf[gdf["ISO_A3"].isin(EUROPE_ISO3)].to_crs(epsg=3857)
    europe.plot(ax=ax, color="#eef1f4", edgecolor="#b8c0c8", linewidth=0.35, zorder=0)
    return "Natural Earth country outlines"


def render_map_png(data: dict, out_path: Path) -> str:
    ASSETS.mkdir(parents=True, exist_ok=True)

    xmin, ymin = TO_3857.transform(EUROPE_BBOX[0], EUROPE_BBOX[1])
    xmax, ymax = TO_3857.transform(EUROPE_BBOX[2], EUROPE_BBOX[3])

    # Wide aspect for landscape PDF page; no suptitle (title lives in PDF text).
    fig, ax = plt.subplots(figsize=(12, 8), dpi=160)
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    ax.set_axis_off()

    basemap_label = _add_basemap(ax)

    price_rows = []
    for e in data["price_lines"]:
        x1, y1 = TO_3857.transform(e["lon1"], e["lat1"])
        x2, y2 = TO_3857.transform(e["lon2"], e["lat2"])
        price_rows.append({"geometry": LineString([(x1, y1), (x2, y2)]), "r": e["r"]})
    if price_rows:
        gpd.GeoDataFrame(price_rows, crs="EPSG:3857").plot(
            ax=ax,
            color="#666666",
            linewidth=0.8,
            linestyle=(0, (6, 4)),
            alpha=0.65,
        )

    flow_rows = []
    max_mw = max(f["mw"] for f in data["flow_lines"])
    for e in data["flow_lines"]:
        x1, y1 = TO_3857.transform(e["lon1"], e["lat1"])
        x2, y2 = TO_3857.transform(e["lon2"], e["lat2"])
        flow_rows.append(
            {
                "geometry": LineString([(x1, y1), (x2, y2)]),
                "mw": e["mw"],
                "lw": 1.2 + (e["mw"] / max_mw) * 4.5,
            }
        )
    for row in flow_rows:
        xs, ys = row["geometry"].xy
        ax.plot(xs, ys, color="#2563a8", linewidth=row["lw"], alpha=0.78, solid_capstyle="round")
        mx, my = (xs[0] + xs[-1]) / 2, (ys[0] + ys[-1]) / 2
        ax.annotate(
            ">",
            (mx, my),
            fontsize=9,
            color="#2563a8",
            ha="center",
            va="center",
            weight="bold",
        )

    max_n = max(c["n"] for c in data["countries"])
    for c in data["countries"]:
        x, y = TO_3857.transform(c["lon"], c["lat"])
        r = 3 + (c["n"] / max_n) * 12
        ax.scatter([x], [y], s=r**2 * 2.2, c="#2563a8", alpha=0.45, edgecolors="#174a7a", linewidths=0.6)
        ax.text(x, y + r * 8000, c["iso"], fontsize=7, ha="center", color="#111", weight="bold")

    legend_items = [
        Line2D([0], [0], color="#2563a8", linewidth=3, label="Physical flow (ENTSO-E, MW)"),
        Line2D([0], [0], color="#666666", linewidth=1.2, linestyle="--", label="Price coupling (r ≥ 0.92)"),
        Line2D([0], [0], marker="o", color="#2563a8", linestyle="None", markersize=6, label="Substation density (OSM)"),
    ]
    ax.legend(handles=legend_items, loc="upper left", framealpha=0.92, fontsize=8)

    fig.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.01)
    fig.savefig(out_path, facecolor="white")
    plt.close(fig)

    preview = out_path.with_name("europe_map_preview.png")
    fig2, ax2 = plt.subplots(figsize=(7, 4.8), dpi=96)
    ax2.imshow(plt.imread(out_path))
    ax2.axis("off")
    fig2.subplots_adjust(0, 0, 1, 1)
    fig2.savefig(preview, facecolor="white")
    plt.close(fig2)
    return basemap_label


def render_price_chart(out_path: Path) -> Path:
    prices = pd.read_parquet(ROOT / "data/processed/entsoe/prices_2025.parquet")
    monthly = (
        prices.assign(month=prices["timestamp"].dt.to_period("M").astype(str))
        .groupby(["month", "zone"])["value"]
        .mean()
        .reset_index()
    )
    zones = ["DE_LU", "FR", "NL", "ES", "PL"]
    fig, ax = plt.subplots(figsize=(10, 4.5), dpi=160)
    for zone in zones:
        sub = monthly[monthly["zone"] == zone].sort_values("month")
        if sub.empty:
            continue
        ax.plot(sub["month"], sub["value"], marker="o", linewidth=1.8, label=zone)
    ax.set_title("Day-ahead prices — monthly average (EUR/MWh)", fontsize=11, loc="left")
    ax.set_ylabel("EUR/MWh")
    ax.tick_params(axis="x", rotation=45, labelsize=7)
    ax.grid(True, alpha=0.25)
    ax.legend(fontsize=8, ncol=3, loc="upper right")
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out_path


def render_corr_chart(out_path: Path) -> Path:
    prices = pd.read_parquet(ROOT / "data/processed/entsoe/prices_2025.parquet")
    wide = prices.pivot_table(index="timestamp", columns="zone", values="value", aggfunc="mean")
    corr = wide.corr(min_periods=24 * 30)
    pairs: list[tuple[str, float]] = []
    for i in corr.columns:
        for j in corr.columns:
            if i >= j:
                continue
            r = corr.loc[i, j]
            if pd.notna(r):
                pairs.append((f"{i} - {j}", float(r)))
    pairs.sort(key=lambda x: -x[1])
    top = pairs[:8]

    fig, ax = plt.subplots(figsize=(10, 4.5), dpi=160)
    labels = [p[0] for p in top]
    vals = [p[1] for p in top]
    ax.barh(labels[::-1], vals[::-1], color="#2563a8", alpha=0.85)
    ax.set_xlim(0.9, 1.0)
    ax.set_title("Strongest day-ahead price correlations (2025)", fontsize=11, loc="left")
    ax.set_xlabel("Pearson r")
    ax.grid(True, axis="x", alpha=0.25)
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out_path


def _load_phase2_stats() -> dict:
    stats: dict = {}
    if FLOW_VALIDATION.exists():
        fv = json.loads(FLOW_VALIDATION.read_text(encoding="utf-8"))
        stats["flow_by_status"] = fv.get("by_status", {})
        stats["graph_flow_edges"] = fv.get("graph_flow_edge_count", 0)
        dup = fv.get("duplicate_exporters", {})
        stats["duplicate_exporter_count"] = len(dup)
    if GRAPH_STATIC.exists():
        g = json.loads(GRAPH_STATIC.read_text(encoding="utf-8"))
        stats["graph"] = g.get("stats", {})
        stats["static_layers"] = g.get("static_layers", {})
    return stats


def render_gem_chart(out_path: Path) -> Path | None:
    gem_files = sorted((ROOT / "data/raw/static/gem").glob("plants_eu_*.parquet"))
    if not gem_files:
        return None
    df = pd.read_parquet(gem_files[-1], columns=["Country/area", "Capacity (MW)", "Status"])
    df["Capacity (MW)"] = pd.to_numeric(df["Capacity (MW)"], errors="coerce")
    oper = df[df["Status"].astype(str).str.lower() == "operating"].copy()
    oper["iso2"] = oper["Country/area"].map(GEM_COUNTRY_TO_ISO2)
    oper = oper.dropna(subset=["iso2", "Capacity (MW)"])
    by_country = oper.groupby("iso2")["Capacity (MW)"].sum().sort_values(ascending=False).head(10)
    if by_country.empty:
        return None

    fig, ax = plt.subplots(figsize=(10, 4.5), dpi=160)
    labels = [str(i) for i in by_country.index[::-1]]
    vals = [v / 1000 for v in by_country.values[::-1]]  # GW
    ax.barh(labels, vals, color="#2563a8", alpha=0.85)
    ax.set_title("Installed operating capacity by country (GEM GIPT, GW)", fontsize=11, loc="left")
    ax.set_xlabel("GW (sum of operating units)")
    ax.grid(True, axis="x", alpha=0.25)
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out_path


def _top_flow_edges(n: int = 10) -> list[list[str]]:
    if not FLOW_VALIDATION.exists():
        return []
    fv = json.loads(FLOW_VALIDATION.read_text(encoding="utf-8"))
    edges = fv.get("graph_flow_edges", [])
    rows = []
    for e in sorted(edges, key=lambda x: -x.get("mw", 0))[:n]:
        rows.append([
            f"{e['from']}->{e['to']}",
            f"{e['mw']:,.0f}",
            e.get("edge_type", "physical_flow").replace("_", " "),
            e.get("validation_status", "-"),
        ])
    return rows


class ReportPDF(FPDF):
    def header(self) -> None:
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(100, 100, 100)
        self.cell(0, 8, _ascii("ENTSO-E 2025 - European Electricity Dependency Mapping"), align="R")
        self.ln(4)

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 8, f"Page {self.page_no()}", align="C")


def _ascii(text: str) -> str:
    return (
        text.replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2194", "-")
        .replace("\u2265", ">=")
        .replace("\u2248", "~")
        .replace("\u2022", "-")
        .replace("\u2026", "...")
    )


def _wrap(pdf: FPDF, text: str, h: float = 5.5) -> None:
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(0, h, _ascii(text))


def _section(pdf: FPDF, title: str) -> None:
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 7, _ascii(title), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1)


def _embed_image(pdf: FPDF, path: Path, max_w: float, max_h: float, *, allow_page_break: bool = True) -> None:
    with Image.open(path) as im:
        w_px, h_px = im.size
    ratio = h_px / w_px
    w = max_w
    h = w * ratio
    if h > max_h:
        h = max_h
        w = h / ratio
    if allow_page_break and pdf.get_y() + h > pdf.page_break_trigger:
        pdf.add_page()
    x = pdf.l_margin + (max_w - w) / 2
    pdf.image(str(path), x=x, y=pdf.get_y(), w=w, h=h)
    pdf.set_y(pdf.get_y() + h + 1)


def _table(
    pdf: FPDF,
    headers: list[str],
    rows: list[list[str] | tuple[str, ...]],
    widths: list[float],
    *,
    header_size: int = 8,
    body_size: int = 7,
    row_h: float = 5,
    page_break: bool = True,
) -> None:
    pdf.set_font("Helvetica", "B", header_size)
    for i, h in enumerate(headers):
        pdf.cell(widths[i], row_h + 1, _ascii(h), border=1)
    pdf.ln()

    pdf.set_font("Helvetica", "", body_size)
    for row in rows:
        if page_break and pdf.get_y() + row_h > pdf.page_break_trigger:
            pdf.add_page()
            pdf.set_font("Helvetica", "B", header_size)
            for i, h in enumerate(headers):
                pdf.cell(widths[i], row_h + 1, _ascii(h), border=1)
            pdf.ln()
            pdf.set_font("Helvetica", "", body_size)
        y0 = pdf.get_y()
        x0 = pdf.l_margin
        max_lines = 1
        cell_lines: list[list[str]] = []
        for i, cell in enumerate(row):
            pdf.set_xy(x0 + sum(widths[:i]), y0)
            txt = _ascii(str(cell))
            lines = pdf.multi_cell(widths[i], row_h, txt, border=0, dry_run=True, output="LINES")
            cell_lines.append(lines)
            max_lines = max(max_lines, len(lines))
        row_height = row_h * max_lines
        if page_break and y0 + row_height > pdf.page_break_trigger:
            pdf.add_page()
            pdf.set_font("Helvetica", "B", header_size)
            for i, h in enumerate(headers):
                pdf.cell(widths[i], row_h + 1, _ascii(h), border=1)
            pdf.ln()
            pdf.set_font("Helvetica", "", body_size)
            y0 = pdf.get_y()
        for i, lines in enumerate(cell_lines):
            x = x0 + sum(widths[:i])
            pdf.rect(x, y0, widths[i], row_height)
            pdf.set_xy(x, y0)
            pdf.multi_cell(widths[i], row_h, "\n".join(lines), border=0)
        pdf.set_xy(x0, y0 + row_height)


def build_pdf(
    map_png: Path,
    price_png: Path,
    corr_png: Path,
    out_path: Path,
    gem_png: Path | None = None,
) -> Path:
    pdf = ReportPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=14)
    zone_rows = load_zone_rows()
    p2 = _load_phase2_stats()
    gs = p2.get("graph", {})
    sl = p2.get("static_layers", {})
    flow_status = p2.get("flow_by_status", {})

    # --- Cover ---
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 10, _ascii("European Electricity Dependency Map"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 7, _ascii("ENTSO-E 2025 - dependency mapping"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "I", 10)
    pdf.cell(0, 5, _ascii(f"{date.today():%d %B %Y} | Supervisor: Stefan"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)

    _wrap(
        pdf,
        "I collected ENTSO-E 2025 time-series for European bidding zones, validated cross-border "
        "flows, built a dependency graph, and added PyPSA-Eur grid and GEM plant data as reference "
        "layers. Dynamic edges come from ENTSO-E; static data is geographic context only.",
        h=5,
    )
    pdf.ln(2)

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 6, "Main results", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 10)
    for b in [
        "Strongest price coupling: LT-LV (r~0.998), BG-RO, HR-SI, ES-PT (r~0.978).",
        f"Graph: {gs.get('nodes', 45)} zones, {gs.get('price_edges', 68)} price edges (r>=0.85), "
        f"{gs.get('flow_edges_validated', 89)} flow edges, {gs.get('structural_edges', 177)} structural edges.",
        "171/177 directed flow pairs are duplicate aggregate exports in ENTSO-E; only PT-ES and IE_SEM-GB are clearly distinct.",
        f"Static: {sl.get('grid_lines_count', 9162)} OSM lines (PyPSA-Eur), 55,720 GEM units (August 2026 GIPT).",
        "GB prices missing for 2025 with current codes. German prices use zone DE_LU.",
    ]:
        _wrap(pdf, f"- {b}", h=5)

    # --- Map ---
    pdf.add_page(orientation="L")
    _section(pdf, "1. Map - flows and price coupling")
    pdf.set_font("Helvetica", "", 9)
    _wrap(
        pdf,
        "Blue lines: top cross-border flows (canonical edges, mean |MW|). Grey dashed: price coupling (r>=0.92). "
        "Circles: OSM substation count. Basemap: Carto Positron.",
        h=4,
    )
    _embed_image(pdf, map_png, max_w=pdf.w - 2 * pdf.l_margin, max_h=168)

    # --- Zone reference ---
    pdf.add_page(orientation="P")
    _section(pdf, "2. Bidding zones")
    pdf.set_font("Helvetica", "", 8)
    _wrap(pdf, "Zone codes in all parquet files. Use DE_LU for Germany.", h=4)
    _table(pdf, ["Zone", "Name", "Country", "Sub-national?"], zone_rows, [28, 68, 22, 24], body_size=7, row_h=4.5)

    # --- Datasets + glossary ---
    pdf.add_page()
    _section(pdf, "3. ENTSO-E datasets")
    _table(
        pdf,
        ["File", "Type", "Unit", "Description", "Coverage"],
        [list(r) for r in DATASET_ROWS],
        [34, 28, 18, 72, 22],
        body_size=6,
        row_h=4,
    )
    pdf.ln(2)
    _section(pdf, "4. Columns and fuel types")
    _table(
        pdf,
        ["Column", "Applies to", "Type", "Meaning"],
        [list(r) for r in COLUMN_ROWS],
        [32, 26, 20, 82],
        body_size=6,
        row_h=4,
    )
    pdf.ln(1)
    _table(pdf, ["PSR", "Name", "Category"], [list(r) for r in PSR_ROWS], [16, 48, 38], body_size=6, row_h=4)

    # --- Price analysis ---
    pdf.add_page()
    _section(pdf, "5. Price analysis (2025)")
    pdf.set_font("Helvetica", "", 9)
    _wrap(
        pdf,
        "High day-ahead price correlation indicates market integration. "
        "I use r>=0.85 as the price-coupling threshold in the graph.",
        h=4,
    )
    _embed_image(pdf, price_png, max_w=190, max_h=88)
    _embed_image(pdf, corr_png, max_w=190, max_h=88)

    # --- Flow validation + graph (one page) ---
    pdf.add_page()
    pdf.set_auto_page_break(auto=False)
    _section(pdf, "6. Flow validation")
    pdf.set_font("Helvetica", "", 8)
    _wrap(
        pdf,
        "Duplicate outgoing series (>=95% identical from the same zone) affect most TSOs.",
        h=3.5,
    )
    _table(
        pdf,
        ["Status", "Pairs", "Meaning"],
        [
            ["duplicate_export", str(flow_status.get("duplicate_export", 171)), "Same as another outgoing border"],
            ["partial", str(flow_status.get("partial", 2)), "Coverage < 90%"],
            ["missing", str(flow_status.get("missing", 4)), "No data"],
            ["ok", str(flow_status.get("ok", 0)), "Distinct series"],
            ["graph edges", str(p2.get("graph_flow_edges", 89)), "One edge per border"],
        ],
        [32, 20, 88],
        body_size=6,
        row_h=3.5,
        page_break=False,
    )
    pdf.set_font("Helvetica", "B", 8)
    pdf.cell(0, 4, "Top flow edges (mean |MW|)", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    flow_rows = _top_flow_edges(4)
    if flow_rows:
        _table(
            pdf, ["Border", "MW", "Type", "Check"], flow_rows,
            [30, 18, 42, 40], body_size=6, row_h=3.5, page_break=False,
        )

    pdf.ln(1)
    _section(pdf, "7. Dependency graph")
    _table(
        pdf,
        ["Layer", "Count", "Source"],
        [
            ["Price coupling", str(gs.get("price_edges", 68)), "prices_2025 (r>=0.85)"],
            ["Physical flow", str(gs.get("flow_edges_validated", 89)), "flows_2025, canonical"],
            ["Structural", str(gs.get("structural_edges", 177)), "zones.yaml"],
            ["Nodes", str(gs.get("nodes", 45)), "zones + OSM centroids"],
        ],
        [32, 18, 110],
        body_size=6,
        row_h=3.5,
        page_break=False,
    )

    pdf.ln(1)
    _section(pdf, "8. Static infrastructure")
    pdf.set_font("Helvetica", "", 8)
    _wrap(
        pdf,
        "PyPSA-Eur OSM grid and GEM GIPT (Aug 2026, CC BY 4.0) - reference layers only, not in edge weights.",
        h=3.5,
    )
    _table(
        pdf,
        ["Source", "Records", "Use"],
        [
            ["PyPSA-Eur OSM", f"{sl.get('grid_lines_count', 9162)} lines", "Substation density"],
            ["GEM GIPT", "55,720 units", "Country capacity on nodes"],
        ],
        [34, 28, 98],
        body_size=6,
        row_h=3.5,
        page_break=False,
    )
    if gem_png and gem_png.exists():
        remaining = pdf.page_break_trigger - pdf.get_y() - 4
        _embed_image(pdf, gem_png, max_w=190, max_h=max(remaining, 40), allow_page_break=False)
        pdf.set_font("Helvetica", "I", 7)
        _wrap(pdf, "Operating GEM capacity by country (GW).", h=3)

    pdf.set_auto_page_break(auto=True, margin=14)

    pdf.output(str(out_path))
    return out_path


def write_map_base64(png_path: Path) -> None:
    preview = png_path.with_name("europe_map_preview.png")
    source = preview if preview.exists() else png_path
    raw = source.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    B64_OUT.write_text(b64, encoding="utf-8")


def update_canvas_preview() -> None:
    if not CANVAS_PATH.exists() or not B64_OUT.exists():
        return
    b64 = B64_OUT.read_text(encoding="utf-8").strip()
    text = CANVAS_PATH.read_text(encoding="utf-8")
    marker = 'const MAP_PNG_B64 = "'
    start = text.find(marker)
    if start < 0:
        return
    end = text.find('";', start + len(marker))
    if end < 0:
        return
    CANVAS_PATH.write_text(text[: start + len(marker)] + b64 + text[end:], encoding="utf-8")


def main() -> None:
    data = _ensure_map_data()
    map_png = ASSETS / "europe_map.png"
    price_png = ASSETS / "monthly_prices.png"
    corr_png = ASSETS / "top_correlations.png"

    gem_png = ASSETS / "gem_capacity.png"

    print("Rendering map (Carto basemap)...")
    basemap = render_map_png(data, map_png)
    print(f"  Basemap: {basemap}")
    print("Rendering charts...")
    render_price_chart(price_png)
    render_corr_chart(corr_png)
    render_gem_chart(gem_png)
    print("Building PDF...")
    build_pdf(map_png, price_png, corr_png, PDF_OUT, gem_png=gem_png)
    write_map_base64(map_png)
    update_canvas_preview()
    print(f"Wrote {PDF_OUT}")
    print(f"Wrote {map_png}")
    print(f"Wrote {B64_OUT} ({B64_OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
