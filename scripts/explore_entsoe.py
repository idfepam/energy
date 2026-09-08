#!/usr/bin/env python3
"""Initial exploratory analysis of 2025 ENTSO-E data for dependency mapping."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed" / "entsoe"
OUT = ROOT / "data" / "manifests" / "exploration_summary.json"


def load_prices() -> pd.DataFrame:
    path = PROCESSED / "prices_2025.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Run: energy-collect validate --year 2025\nMissing {path}")
    df = pd.read_parquet(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def load_flows() -> pd.DataFrame:
    path = PROCESSED / "flows_2025.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Missing {path}")
    df = pd.read_parquet(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def load_generation() -> pd.DataFrame:
    path = PROCESSED / "generation_2025.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Missing {path}")
    df = pd.read_parquet(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def price_summary(prices: pd.DataFrame) -> dict:
    pivot = prices.pivot_table(index="timestamp", columns="zone", values="value", aggfunc="mean")
    corr = pivot.corr()

    # Top correlated zone pairs (excluding self)
    pairs = []
    zones = corr.columns.tolist()
    for i, z1 in enumerate(zones):
        for z2 in zones[i + 1 :]:
            pairs.append({"zone_a": z1, "zone_b": z2, "correlation": round(float(corr.loc[z1, z2]), 3)})
    pairs.sort(key=lambda x: abs(x["correlation"]), reverse=True)

    stats = prices.groupby("zone")["value"].agg(["mean", "std", "min", "max"]).round(2)
    stats_dict = stats.to_dict(orient="index")

    return {
        "zones": len(zones),
        "hours": len(pivot),
        "top_correlated_pairs": pairs[:15],
        "lowest_correlated_pairs": pairs[-5:],
        "zone_stats": {k: v for k, v in list(stats_dict.items())[:5]},  # sample
    }


def flow_summary(flows: pd.DataFrame) -> dict:
    flows = flows.copy()
    flows["pair"] = flows["from_zone"] + ">" + flows["to_zone"]

    # Mean absolute flow per border pair
    mean_flow = (
        flows.groupby("pair")["value"]
        .apply(lambda x: x.abs().mean())
        .sort_values(ascending=False)
    )

    top_pairs = [
        {"pair": pair, "mean_abs_flow_mw": round(float(val), 1)}
        for pair, val in mean_flow.head(20).items()
    ]

    return {
        "border_pairs": flows["pair"].nunique(),
        "total_observations": len(flows),
        "top_flow_pairs": top_pairs,
    }


def generation_summary(gen: pd.DataFrame) -> dict:
    if "psr_type" not in gen.columns:
        # Wide format with psr in separate column or multiple value columns
        cols = [c for c in gen.columns if c not in ("timestamp", "zone", "value", "dataset", "period_start", "period_end")]
        return {"columns": list(gen.columns), "rows": len(gen)}

    by_fuel = gen.groupby("psr_type")["value"].mean().sort_values(ascending=False)
    top_fuels = [
        {"psr_type": k, "mean_mw": round(float(v), 1)}
        for k, v in by_fuel.head(10).items()
    ]
    return {"top_generation_types_eu_avg": top_fuels}


def main() -> None:
    summary: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "year": 2025,
    }

    print("Loading prices...")
    prices = load_prices()
    summary["prices"] = price_summary(prices)
    print(f"  {summary['prices']['zones']} zones, {summary['prices']['hours']} hours")

    print("Loading flows...")
    flows = load_flows()
    summary["flows"] = flow_summary(flows)
    print(f"  {summary['flows']['border_pairs']} border pairs")

    print("Loading generation...")
    gen = load_generation()
    summary["generation"] = generation_summary(gen)

    OUT.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\nSummary written to {OUT}")

    print("\n--- Top price-correlated zone pairs ---")
    for p in summary["prices"]["top_correlated_pairs"][:5]:
        print(f"  {p['zone_a']} ↔ {p['zone_b']}: r={p['correlation']}")

    print("\n--- Top cross-border flow pairs (mean |MW|) ---")
    for p in summary["flows"]["top_flow_pairs"][:5]:
        print(f"  {p['pair']}: {p['mean_abs_flow_mw']} MW")


if __name__ == "__main__":
    main()
