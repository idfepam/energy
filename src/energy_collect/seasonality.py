"""Seasonal decomposition of ENTSO-E time series."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from energy_collect.config import AppConfig

CHART_ZONES = ["DE_LU", "FR", "NL", "ES", "PL"]
QUARTER_LABELS = ["Q1 (Jan–Mar)", "Q2 (Apr–Jun)", "Q3 (Jul–Sep)", "Q4 (Oct–Dec)"]


def _load_series(config: AppConfig, year: int, dataset: str) -> pd.DataFrame:
    path = config.data_root / "processed" / "entsoe" / f"{dataset}_{year}.parquet"
    if not path.exists():
        raise FileNotFoundError(path)
    df = pd.read_parquet(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def hod_deseasonalize(series: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Remove mean hour-of-day profile; return (seasonal, residual)."""
    hour = series.index.hour
    seasonal = series.groupby(hour).transform("mean")
    return seasonal, series - seasonal


def dow_deseasonalize(series: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Remove mean day-of-week profile."""
    dow = series.index.dayofweek
    seasonal = series.groupby(dow).transform("mean")
    return seasonal, series - seasonal


def moy_deseasonalize(series: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Remove mean month-of-year profile (captures quarterly/seasonal level shifts)."""
    month = series.index.month
    seasonal = series.groupby(month).transform("mean")
    return seasonal, series - seasonal


def _seasonal_strength(observed: pd.Series, seasonal: pd.Series) -> float:
    var_obs = float(observed.var())
    if var_obs <= 0 or np.isnan(var_obs):
        return 0.0
    return float(max(0.0, 1.0 - (observed - seasonal).var() / var_obs))


def _incremental_strength(before: pd.Series, after: pd.Series) -> float:
    var_before = float(before.var())
    if var_before <= 0 or np.isnan(var_before):
        return 0.0
    return float(max(0.0, 1.0 - after.var() / var_before))


def calendar_month_profile(ts: pd.Series) -> list[float]:
    """Mean value for each calendar month (1–12), NaN months filled from overall mean."""
    overall = float(ts.mean())
    by_month = ts.groupby(ts.index.month).mean()
    return [round(float(by_month.get(m, overall)), 2) for m in range(1, 13)]


def quarter_profile(ts: pd.Series) -> list[float]:
    """Mean value for each calendar quarter Q1–Q4."""
    overall = float(ts.mean())
    q = ((ts.index.month - 1) // 3) + 1
    by_q = ts.groupby(q).mean()
    return [round(float(by_q.get(i, overall)), 2) for i in range(1, 5)]


def decompose_zone_series(ts: pd.Series) -> dict[str, pd.Series]:
    """
    Multi-scale seasonal decomposition:
    hour-of-day → day-of-week → month-of-year → 7-day rolling trend → residual.
    """
    ts = ts.sort_index().astype(float)
    ts = ts[~ts.index.duplicated(keep="first")]

    hod_seasonal, after_hod = hod_deseasonalize(ts)
    dow_seasonal, after_dow = dow_deseasonalize(after_hod)
    moy_seasonal, after_moy = moy_deseasonalize(after_dow)
    trend = after_moy.rolling(24 * 7, center=True, min_periods=24).mean()
    final_residual = after_moy - trend

    return {
        "observed": ts,
        "seasonal_hod": hod_seasonal,
        "seasonal_dow": dow_seasonal,
        "seasonal_moy": moy_seasonal,
        "trend": trend,
        "residual": final_residual,
    }


def run_seasonality_decomposition(
    config: AppConfig,
    year: int,
    *,
    dataset: str = "prices",
) -> dict[str, Any]:
    df = _load_series(config, year, dataset)
    out_dir = config.data_root / "processed" / "entsoe"
    out_dir.mkdir(parents=True, exist_ok=True)

    residual_frames: list[pd.DataFrame] = []
    zone_summaries: list[dict[str, Any]] = []
    hourly_profiles: dict[str, list[float]] = {}
    monthly_profiles: dict[str, list[float]] = {}
    quarterly_profiles: dict[str, list[float]] = {}

    for zone, grp in df.groupby("zone"):
        ts = grp.set_index("timestamp")["value"].sort_index()
        if len(ts) < 24 * 14:
            continue

        parts = decompose_zone_series(ts)
        residual_frames.append(
            pd.DataFrame(
                {
                    "timestamp": parts["residual"].index,
                    "zone": zone,
                    "value": parts["residual"].values,
                }
            )
        )

        hod_profile = parts["observed"].groupby(parts["observed"].index.hour).mean()
        hourly_profiles[zone] = [
            round(float(v), 2) for v in hod_profile.reindex(range(24), fill_value=np.nan)
        ]
        monthly_profiles[zone] = calendar_month_profile(parts["observed"])
        quarterly_profiles[zone] = quarter_profile(parts["observed"])

        after_hod = parts["observed"] - parts["seasonal_hod"]
        after_dow = after_hod - parts["seasonal_dow"]
        after_moy = after_dow - parts["seasonal_moy"]

        zone_summaries.append(
            {
                "zone": zone,
                "hours": int(len(ts)),
                "mean": round(float(parts["observed"].mean()), 2),
                "hod_strength": round(_seasonal_strength(parts["observed"], parts["seasonal_hod"]), 3),
                "dow_strength": round(_incremental_strength(after_hod, after_dow), 3),
                "moy_strength": round(_incremental_strength(after_dow, after_moy), 3),
                "quarter_spread": round(float(max(quarterly_profiles[zone]) - min(quarterly_profiles[zone])), 2),
                "residual_std": round(float(parts["residual"].std()), 3),
            }
        )

    residual_path = out_dir / f"{dataset}_deseasonalised_{year}.parquet"
    if residual_frames:
        pd.concat(residual_frames, ignore_index=True).to_parquet(residual_path, index=False)

    unit = "EUR/MWh" if dataset == "prices" else "MW"
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "year": year,
        "dataset": dataset,
        "unit": unit,
        "zones": len(zone_summaries),
        "method": (
            "hour-of-day + day-of-week + month-of-year mean removal, "
            "then 7-day rolling trend; residual used for TE"
        ),
        "residual_file": str(residual_path),
        "zone_summaries": sorted(zone_summaries, key=lambda x: -x["hod_strength"]),
        "top_moy_strength": sorted(zone_summaries, key=lambda x: -x["moy_strength"])[:10],
        "hourly_profiles": hourly_profiles,
        "monthly_profiles": {k: monthly_profiles[k] for k in CHART_ZONES if k in monthly_profiles},
        "quarterly_profiles": {k: quarterly_profiles[k] for k in CHART_ZONES if k in quarterly_profiles},
        "quarter_labels": QUARTER_LABELS,
        "calendar_month_labels": [
            "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
        ],
    }

    manifest_dir = config.data_root / "manifests" / "dashboard"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    out = manifest_dir / f"seasonality_{dataset}_{year}.json"
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    summary["output_path"] = str(out)
    return summary


def run_all_seasonality(config: AppConfig, year: int) -> dict[str, Any]:
    """Decompose prices and load (when load parquet exists)."""
    results: dict[str, Any] = {"prices": run_seasonality_decomposition(config, year, dataset="prices")}
    load_path = config.data_root / "processed" / "entsoe" / f"load_{year}.parquet"
    if load_path.exists():
        results["load"] = run_seasonality_decomposition(config, year, dataset="load")
    return results
