from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from energy_collect.config import AppConfig
from energy_collect.storage.manifest import Manifest

logger = logging.getLogger(__name__)

HOURS_2025 = 8784  # non-leap year


def validate_collection(config: AppConfig, year: int) -> dict:
    manifest = Manifest(config.data_root / "manifests" / "collection.db")
    jobs = manifest.list_jobs()
    year_prefix = f"{year}-"

    report: dict = {
        "year": year,
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "manifest_summary": manifest.summary(),
        "datasets": {},
    }

    for ds_name, ds_cfg in config.datasets.items():
        ds_report = {
            "scope": ds_cfg["scope"],
            "files": 0,
            "total_rows": 0,
            "issues": [],
        }
        pattern = config.data_root / "raw" / "entsoe" / ds_name
        if not pattern.exists():
            ds_report["issues"].append("no data directory")
            report["datasets"][ds_name] = ds_report
            continue

        for parquet_file in pattern.rglob("*.parquet"):
            if year_prefix not in parquet_file.name and str(year) not in str(
                parquet_file
            ):
                # border pair monthly files use YYYY-MM-DD in name
                if not any(f"{year}-" in part for part in parquet_file.parts):
                    continue
            try:
                df = pd.read_parquet(parquet_file)
                ds_report["files"] += 1
                ds_report["total_rows"] += len(df)
                if "timestamp" in df.columns and ds_cfg["scope"] == "zone":
                    ts = pd.to_datetime(df["timestamp"], utc=True)
                    year_mask = ts.dt.year == year
                    hour_count = ts[year_mask].nunique()
                    if hour_count < HOURS_2025 * 0.95:
                        ds_report["issues"].append(
                            f"{parquet_file.name}: only {hour_count} unique hours"
                        )
            except Exception as exc:
                ds_report["issues"].append(f"{parquet_file.name}: {exc}")

        report["datasets"][ds_name] = ds_report

    out_path = config.data_root / "manifests" / f"validation_{year}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2))
    logger.info("Validation report written to %s", out_path)
    return report


def consolidate_processed(config: AppConfig, year: int) -> None:
    """Merge raw parquet files into analysis-ready processed datasets."""
    processed_dir = config.data_root / "processed" / "entsoe"
    processed_dir.mkdir(parents=True, exist_ok=True)
    year_prefix = f"{year}-"

    mappings = {
        "day_ahead_prices": "prices",
        "crossborder_flows": "flows",
        "actual_load": "load",
        "generation_actual": "generation",
    }

    for dataset, out_name in mappings.items():
        src_dir = config.data_root / "raw" / "entsoe" / dataset
        if not src_dir.exists():
            continue
        frames = []
        for f in src_dir.rglob("*.parquet"):
            if year_prefix in f.name or str(year) in str(f.parent):
                frames.append(pd.read_parquet(f))
        if frames:
            combined = pd.concat(frames, ignore_index=True)
            out_path = processed_dir / f"{out_name}_{year}.parquet"
            combined.to_parquet(out_path, index=False)
            logger.info("Wrote %s (%s rows)", out_path, len(combined))
