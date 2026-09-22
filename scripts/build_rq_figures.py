#!/usr/bin/env python3
"""Render the RQ1-RQ3 answer figures from comovement_{year}.json.

Output: docs/dashboard/figures/*.png (inside docs/dashboard so GitHub Pages
serves them alongside the dashboard, and the markdown answers can embed them).

    python3 scripts/build_rq_figures.py --year 2025
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "dashboard" / "figures"

BLUE = "#2f6fd0"
LIGHT = "#5fa8d3"
GREY = "#d7e1ec"
RED = "#c0392b"
ORANGE = "#e67e22"
GREEN = "#2e8b57"

BLOC_COLORS = [
    "#2f6fd0", "#e67e22", "#2e8b57", "#c0392b",
    "#8e44ad", "#16a085", "#d4ac0d", "#7f8c8d",
]

plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "axes.edgecolor": "#c7d0da",
        "axes.labelcolor": "#2b3440",
        "text.color": "#2b3440",
        "xtick.color": "#5a6672",
        "ytick.color": "#5a6672",
        "axes.grid": True,
        "grid.color": "#eef2f6",
        "figure.facecolor": "white",
        "savefig.facecolor": "white",
    }
)


def _save(fig: plt.Figure, name: str) -> Path:
    for ax in fig.get_axes():
        ax.set_axisbelow(True)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"  {path.relative_to(ROOT)}")
    return path


# ---------------------------------------------------------------- RQ1


def rq1_figure(report: dict) -> None:
    res = report["rq1"]["residuals"]
    lev = report["rq1"]["levels"]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.0), gridspec_kw={"width_ratios": [1, 1.35]})

    # Left: variance partition.
    labels = ["Deseasonalised\n(shared shocks)", "Raw levels\n(shocks + calendar)"]
    market = [100 * res["variance_market_mode"], 100 * lev["variance_market_mode"]]
    cluster = [100 * res["variance_cluster_modes"], 100 * lev["variance_cluster_modes"]]
    noise = [100 * res["variance_noise_bulk"], 100 * lev["variance_noise_bulk"]]
    y = np.arange(2)
    ax1.set_axisbelow(True)
    ax1.barh(y, market, color=BLUE, label="Europe-wide mode", zorder=3)
    ax1.barh(y, cluster, left=market, color=LIGHT, label="Cluster modes", zorder=3)
    ax1.barh(y, noise, left=np.add(market, cluster), color=GREY, label="Noise", zorder=3)
    for i in range(2):
        ax1.text(market[i] / 2, i, f"{market[i]:.0f}%", ha="center", va="center", color="white", fontweight="bold", zorder=4)
        ax1.text(market[i] + cluster[i] / 2, i, f"{cluster[i]:.0f}%", ha="center", va="center", color="white", fontsize=8, zorder=4)
        ax1.text(100 - noise[i] / 2, i, f"{noise[i]:.0f}%", ha="center", va="center", color="#5a6672", fontsize=8, zorder=4)
    ax1.set_yticks(y, labels)
    ax1.set_xlim(0, 100)
    ax1.set_xlabel("% of total variance across 43 zones")
    ax1.set_title("How the co-movement splits", loc="left", fontweight="bold")
    ax1.legend(loc="lower center", bbox_to_anchor=(0.5, -0.42), ncol=3, frameon=False, fontsize=8)
    ax1.grid(axis="y", visible=False)
    ax1.invert_yaxis()

    # Right: eigenvalue spectrum vs the surrogate band.
    n = 16
    eig = res["eigenvalues"][:n]
    q95 = res["null_q95"][:n]
    k = res["k_significant_95"]
    x = np.arange(1, n + 1)
    colors = [BLUE if i < k else GREY for i in range(n)]
    ax2.bar(x, eig, color=colors, width=0.7,
            label="Observed eigenvalue (blue = supported)")
    ax2.plot(x, q95, color=RED, lw=1.8, marker="o", ms=3, label="Surrogate 95th percentile")
    ax2.set_yscale("log")
    ax2.set_xticks(x)
    ax2.set_xticklabels([str(i) for i in x], fontsize=8)
    ax2.set_xlabel("Eigenvalue rank")
    ax2.set_ylabel("Eigenvalue (log scale)")
    ax2.set_title(f"{k} modes clear the noise band", loc="left", fontweight="bold")
    ax2.legend(frameon=False, fontsize=8, loc="upper right")
    ax2.set_ylim(min(eig) * 0.5, eig[0] * 2.6)
    ax2.annotate(
        f"λ1 = {eig[0]:.1f}  ({100 * res['variance_market_mode']:.0f}% of variance)\nthe Europe-wide mode",
        xy=(1, eig[0]), xytext=(2.2, eig[0] * 0.30),
        fontsize=8, color=BLUE,
        arrowprops=dict(arrowstyle="->", color=BLUE, lw=1),
    )
    ax2.annotate(
        "λ7 falls inside the band\n→ spectrum stops at 6",
        xy=(7, eig[6]), xytext=(8.4, eig[6] * 1.9),
        fontsize=8, color="#5a6672",
        arrowprops=dict(arrowstyle="->", color="#9aa7b5", lw=1),
    )
    fig.suptitle(
        "RQ1 — One Europe-wide mode (47%) plus five supported cluster dimensions (29%)",
        x=0.01, ha="left", fontsize=11.5, fontweight="bold",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    _save(fig, "rq1_modes.png")


def rq1_loadings_figure(report: dict) -> None:
    modes = report["rq1"]["modes_residual"][:6]
    fig, axes = plt.subplots(2, 3, figsize=(11, 5.0))
    titles = {
        1: "Mode 1 — Europe-wide market mode",
        2: "Mode 2 — Nordic",
        3: "Mode 3 — Italy",
        4: "Mode 4 — Iberia + France",
        5: "Mode 5 — Baltics vs Nordic",
        6: "Mode 6 — Iberia + Baltics",
    }
    for ax, mode in zip(axes.ravel(), modes):
        rows = mode["loadings"][:8][::-1]
        vals = [r["loading"] for r in rows]
        names = [r["zone"] for r in rows]
        ax.barh(range(len(vals)), vals, color=[BLUE if v > 0 else RED for v in vals])
        ax.set_yticks(range(len(vals)), names, fontsize=7.5)
        ax.axvline(0, color="#9aa7b5", lw=0.8)
        ax.set_title(
            f"{titles.get(mode['mode'], 'Mode ' + str(mode['mode']))}  ·  {100 * mode['explained']:.1f}%",
            loc="left", fontsize=9, fontweight="bold",
        )
        ax.grid(axis="y", visible=False)
        ax.tick_params(axis="x", labelsize=7.5)
    fig.suptitle(
        "RQ1 — What each supported mode is  (eigenvector loadings; blue positive, red negative)",
        x=0.01, ha="left", fontsize=11.5, fontweight="bold",
    )
    fig.text(
        0.01, -0.02,
        "Mode 1 has all 43 loadings positive — a true Europe-wide factor. Every later mode changes sign, so it separates blocs.",
        fontsize=8.5, color="#5a6672",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    _save(fig, "rq1_loadings.png")


# ---------------------------------------------------------------- RQ2


def rq2_figure(report: dict) -> None:
    rq2 = report["rq2"]
    rows = rq2["seasons"] + rq2["hour_blocks"]
    joint = rq2["season_hour"]
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7.4), gridspec_kw={"height_ratios": [1, 1]})

    def short(label: str) -> str:
        return (
            label.replace(" (Dec-Feb)", "").replace(" (Mar-May)", "")
            .replace(" (Jun-Aug)", "").replace(" (Sep-Nov)", "")
            .replace(" UTC", "").replace("Summer / ", "Sum/").replace("Winter / ", "Win/")
            .replace("Spring / ", "Spr/").replace("Autumn / ", "Aut/")
        )

    all_rows = rows + joint
    labels = [short(r["label"]) for r in all_rows]
    x = np.arange(len(all_rows))
    ari = [r["ari"] for r in all_rows]
    p05 = [r["null_p05"] for r in all_rows]
    med = [r["null_median"] for r in all_rows]
    colors = [RED if r["reorganised"] else BLUE for r in all_rows]

    ax1.bar(x, ari, color=colors, width=0.7, label="Observed ARI (red = reorganises)")
    ax1.plot(x, p05, color=ORANGE, lw=1.6, ls="--", label="Null 5th percentile — the bar to clear")
    ax1.plot(x, med, color="#9aa7b5", lw=1.1, label="Null median (expected from sample size alone)")
    ax1.axvline(3.5, color="#c7d0da", lw=1)
    ax1.axvline(7.5, color="#c7d0da", lw=1)
    for pos, text in ((1.5, "seasons"), (5.5, "hour blocks"), (15.5, "season × hour-block cells")):
        ax1.text(pos, 1.03, text, ha="center", fontsize=8.5, color="#5a6672", style="italic")
    ax1.set_xticks(x)
    ax1.set_xticklabels([])
    ax1.set_xlim(-0.8, len(all_rows) - 0.2)
    ax1.set_ylim(0, 1.0)
    ax1.set_ylabel("Adjusted Rand Index\nvs the full-year partition")
    ax1.set_title("The partition holds everywhere except summer", loc="left", fontweight="bold", pad=22)
    ax1.legend(frameon=False, fontsize=8.5, loc="upper center", bbox_to_anchor=(0.5, -0.04), ncol=3)
    ax1.grid(axis="x", visible=False)

    share = [100 * r["market_mode_share"] for r in all_rows]
    ax2.bar(x, share, color=[RED if s == min(share) else (GREEN if s == max(share) else LIGHT) for s in share], width=0.7)
    ax2.set_xticks(x, labels, rotation=55, ha="right", fontsize=8)
    ax2.set_xlim(-0.8, len(all_rows) - 0.2)
    ax2.set_ylabel("Share of variance in the\nEurope-wide mode (%)")
    ax2.set_title("What actually moves with the clock is the strength of the common mode", loc="left", fontweight="bold")
    ax2.grid(axis="x", visible=False)
    lo_i = int(np.argmin(share))
    hi_i = int(np.argmax(share))
    ax2.annotate(f"strongest {share[hi_i]:.0f}% — night", xy=(hi_i, share[hi_i]),
                 xytext=(hi_i - 3.6, share[hi_i] + 9), fontsize=8.5, color=GREEN, fontweight="bold",
                 arrowprops=dict(arrowstyle="->", color=GREEN, lw=1.2))
    ax2.annotate(f"weakest {share[lo_i]:.0f}% — summer midday", xy=(lo_i, share[lo_i]),
                 xytext=(lo_i - 7.5, share[lo_i] + 22), fontsize=8.5, color=RED, fontweight="bold",
                 arrowprops=dict(arrowstyle="->", color=RED, lw=1.2))
    ax2.set_ylim(0, 72)

    fig.suptitle(
        "RQ2 — The 8 blocs persist across every season and hour block; only summer daylight reorganises",
        x=0.01, ha="left", fontsize=11.5, fontweight="bold",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.955), h_pad=3.4)
    _save(fig, "rq2_persistence.png")


def _fan_out(
    geo: dict[str, tuple[float, float]], zones: list[str]
) -> tuple[dict[str, tuple[float, float]], set[str]]:
    """Spread zones that share a centroid around it, so none sit on top of another.

    `zone_geo.parquet` gives country centroids, so all five Norwegian and all six
    Italian bidding zones land on the same point. Fanning them into a small ring
    keeps the country position honest while making every zone visible.
    """
    groups: dict[tuple[float, float], list[str]] = {}
    for zone in zones:
        if zone in geo:
            groups.setdefault((round(geo[zone][0], 3), round(geo[zone][1], 3)), []).append(zone)
    out: dict[str, tuple[float, float]] = {}
    fanned: set[str] = set()
    for (lon, lat), members in groups.items():
        if len(members) == 1:
            out[members[0]] = (lon, lat)
            continue
        radius = 1.15 + 0.12 * len(members)
        for i, zone in enumerate(sorted(members)):
            angle = 2 * np.pi * i / len(members) - np.pi / 2
            out[zone] = (lon + radius * np.cos(angle) * 1.45, lat + radius * np.sin(angle))
            fanned.add(zone)
    return out, fanned


def rq2_map_figure(report: dict, geo: dict[str, tuple[float, float]]) -> None:
    clusters = report["rq2"]["clusters"]
    stability = {r["zone"]: r["stability"] for r in report["rq2"]["zone_stability"]}
    all_zones = [z for c in clusters for z in c["members"]]
    placed, fanned = _fan_out(geo, all_zones)

    fig, ax = plt.subplots(figsize=(9.6, 8.4))
    handles = []
    for i, cluster in enumerate(clusters):
        color = BLOC_COLORS[i % len(BLOC_COLORS)]
        for zone in cluster["members"]:
            if zone not in placed:
                continue
            lon, lat = placed[zone]
            ax.scatter(lon, lat, s=460, color=color, edgecolor="white", linewidth=1.4, zorder=3,
                       alpha=0.45 + 0.55 * stability.get(zone, 1.0))
            label = zone.replace("IT_", "").replace("IE_SEM", "IE")
            ax.annotate(label, (lon, lat), fontsize=7.4 if len(label) <= 4 else 6.0,
                        ha="center", va="center", color="white", fontweight="bold", zorder=4)
        handles.append(Line2D([], [], marker="o", ls="", color=color, ms=10,
                              label=f"{cluster['name']} ({cluster['size']})"))
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title(
        "RQ2 — The eight price blocs of 2025",
        loc="left", fontsize=12.5, fontweight="bold", pad=40,
    )
    ax.set_aspect(1.45)
    ax.legend(handles=handles, frameon=False, fontsize=8.5, ncol=3,
              loc="upper center", bbox_to_anchor=(0.5, -0.09))
    ax.text(
        0.0, 1.015,
        "Paler fill = the zone changes bloc more often across seasons and hours. "
        "Italian zones are labelled without the IT_ prefix.\n"
        f"The {len(fanned)} zones that share a country centroid (Norwegian, Swedish, Italian, Danish) "
        "are fanned around it so each stays visible.",
        transform=ax.transAxes, fontsize=8, color="#5a6672", va="bottom",
    )
    fig.tight_layout()
    _save(fig, "rq2_blocs.png")


# ---------------------------------------------------------------- RQ3


def rq3_figure(report: dict) -> None:
    rq3 = report["rq3"]
    prof = rq3["hop_profile"]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.5, 4.9), gridspec_kw={"width_ratios": [1, 1.15]})

    hops = [r["hops"] for r in prof]
    ax1.bar(hops, [r["convergence"] for r in prof], color=GREY, width=0.65,
            label="Share of hours at an identical price")
    ax1.plot(hops, [r["r_levels"] for r in prof], color=BLUE, lw=2, marker="o", ms=4, label="r — price levels")
    ax1.plot(hops, [r["r_residual"] for r in prof], color=LIGHT, lw=2, ls="--", marker="o", ms=4,
             label="r — deseasonalised shocks")
    for r in prof:
        ax1.annotate(str(r["pairs"]), (r["hops"], r["r_levels"]), textcoords="offset points",
                     xytext=(0, 8), ha="center", fontsize=6.5, color="#9aa7b5")
    ax1.set_xticks(hops)
    ax1.set_ylim(0, 1)
    ax1.set_xlabel("Hops between zones in the interconnection graph")
    ax1.set_ylabel("Correlation / share of hours")
    ax1.set_title("Correlation decays with every hop", loc="left", fontweight="bold")
    ax1.legend(frameon=False, fontsize=8.5, loc="upper right")
    ax1.grid(axis="x", visible=False)
    ax1.text(0.0, -0.20, "Grey numbers above each point = zone pairs at that distance.",
             transform=ax1.transAxes, ha="left", fontsize=7.5, color="#9aa7b5")

    under = rq3["under_coupled"][:7]
    over = rq3["over_coupled"][:7]
    names = [f"{r['a']}–{r['b']}" for r in under][::-1] + [""] + [f"{r['a']}–{r['b']}" for r in over][::-1]
    vals = [r["r_levels"] for r in under][::-1] + [0] + [r["r_levels"] for r in over][::-1]
    cols = [RED] * len(under) + ["white"] + [GREEN] * len(over)
    y = np.arange(len(names))
    ax2.barh(y, vals, color=cols, height=0.68)
    ax2.set_yticks(y, names, fontsize=7.5)
    ax2.axvline(rq3["adjacent_mean_r"], color=BLUE, ls="--", lw=1.2)
    gap = len(under)  # the blank spacer row between the two groups
    ax2.text(rq3["adjacent_mean_r"] - 0.02, gap,
             f"mean over all direct borders  {rq3['adjacent_mean_r']:.2f}",
             fontsize=8, color=BLUE, ha="right", va="center")
    for i, (val, row) in enumerate(zip(vals, under[::-1] + [None] + over[::-1])):
        if row is None:
            continue
        ax2.text(val + 0.012, i, f"{val:.2f}", va="center", fontsize=7.5, color="#5a6672")
    ax2.set_xlim(0, 1.16)
    ax2.set_xlabel("Price correlation (levels)")
    ax2.set_title("Where topology and price disagree", loc="left", fontweight="bold")
    ax2.grid(axis="y", visible=False)
    ax2.legend(
        handles=[
            Line2D([], [], marker="s", ls="", color=GREEN, ms=8, label="No direct border, strong coupling"),
            Line2D([], [], marker="s", ls="", color=RED, ms=8, label="Direct border, weak coupling"),
        ],
        frameon=False, fontsize=8.5, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=2,
    )

    fig.suptitle(
        f"RQ3 — Co-movement follows the grid (AUC {rq3['auc_levels']:.2f}, Mantel r {rq3['mantel']['r']:.2f}) "
        "but a line is neither sufficient nor necessary",
        x=0.01, ha="left", fontsize=11.5, fontweight="bold",
    )
    fig.tight_layout(rect=(0, 0.03, 1, 0.93))
    _save(fig, "rq3_topology.png")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2025)
    args = parser.parse_args()

    path = ROOT / "data" / "manifests" / f"comovement_{args.year}.json"
    if not path.exists():
        raise SystemExit(
            f"{path} not found — run:\n"
            f"  PYTHONPATH=src python3 -m energy_collect.cli analyze-comovement --year {args.year}"
        )
    report = json.loads(path.read_text(encoding="utf-8"))

    geo: dict[str, tuple[float, float]] = {}
    geo_path = ROOT / "data" / "processed" / "static" / "zone_geo.parquet"
    if geo_path.exists():
        import pandas as pd

        frame = pd.read_parquet(geo_path)
        geo = {
            row.zone_code: (float(row.centroid_lon), float(row.centroid_lat))
            for row in frame.itertuples()
            if row.centroid_lon == row.centroid_lon
        }

    print("Writing figures:")
    rq1_figure(report)
    rq1_loadings_figure(report)
    rq2_figure(report)
    if geo:
        rq2_map_figure(report, geo)
    else:
        print("  (skipped rq2_blocs.png — zone_geo.parquet not found)")
    rq3_figure(report)


if __name__ == "__main__":
    main()
