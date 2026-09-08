#!/usr/bin/env python3
"""Profile collected ENTSO-E data and write a summary report."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "entsoe"
OUT = ROOT / "data" / "manifests" / "data_profile.json"

DATASETS = {
    "day_ahead_prices": {"unit": "EUR/MWh", "scope": "zone"},
    "actual_load": {"unit": "MW", "scope": "zone"},
    "generation_actual": {"unit": "MW", "scope": "zone", "has_psr": True},
    "imbalance_prices": {"unit": "EUR/MWh", "scope": "zone"},
    "crossborder_flows": {"unit": "MW", "scope": "border"},
    "scheduled_exchanges": {"unit": "MW", "scope": "border"},
    "net_transfer_capacity": {"unit": "MW", "scope": "border"},
}


def profile_dataset(name: str, cfg: dict) -> dict:
    ddir = RAW / name
    if not ddir.exists():
        return {"status": "missing", "files": 0}

    files = list(ddir.rglob("*.parquet"))
    if not files:
        return {"status": "empty", "files": 0}

    total_rows = 0
    zones: set[str] = set()
    pairs: set[str] = set()
    ts_min, ts_max = None, None
    sample_cols: list[str] = []

    for f in files[:200]:  # sample for speed on large sets
        df = pd.read_parquet(f)
        total_rows += len(df)
        if sample_cols == []:
            sample_cols = list(df.columns)

        if "timestamp" in df.columns:
            ts = pd.to_datetime(df["timestamp"], utc=True)
            lo, hi = ts.min(), ts.max()
            ts_min = lo if ts_min is None else min(ts_min, lo)
            ts_max = hi if ts_max is None else max(ts_max, hi)

        if "zone" in df.columns:
            zones.update(df["zone"].dropna().unique())
        if "from_zone" in df.columns:
            pairs.update(
                df["from_zone"].astype(str) + ">" + df["to_zone"].astype(str)
            )

    # Extrapolate row count if we sampled
    if len(files) > 200:
        avg_rows = total_rows / min(200, len(files))
        total_rows = int(avg_rows * len(files))

    result = {
        "status": "ok",
        "files": len(files),
        "estimated_rows": total_rows,
        "unit": cfg["unit"],
        "scope": cfg["scope"],
        "columns": sample_cols,
        "time_range": {
            "start": str(ts_min) if ts_min else None,
            "end": str(ts_max) if ts_max else None,
        },
    }
    if zones:
        result["zones"] = sorted(zones)
        result["zone_count"] = len(zones)
    if pairs:
        result["border_pairs"] = len(pairs)
    return result


def main() -> None:
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "year": 2025,
        "source": "ENTSO-E Transparency Platform",
        "datasets": {},
    }

    for name, cfg in DATASETS.items():
        report["datasets"][name] = profile_dataset(name, cfg)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str))
    print(f"Profile written to {OUT}")

    for name, info in report["datasets"].items():
        if info.get("status") == "ok":
            print(
                f"  {name}: {info['files']} files, "
                f"~{info['estimated_rows']:,} rows, "
                f"{info.get('zone_count', info.get('border_pairs', '?'))} "
                f"{'zones' if info['scope']=='zone' else 'pairs'}"
            )
        else:
            print(f"  {name}: {info['status']}")


if __name__ == "__main__":
    main()
