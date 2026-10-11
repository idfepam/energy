"""
Price shape across bidding zones: calendar profiles, tails and timing.

Adapts the structural validation metrics of Cäsar, Neumann & Zwickl-Bernhard
(2026), "Can shadow prices from energy system optimization models serve as
reliable electricity price indicators?" (SSRN 10.2139/ssrn.6714235), from a
model-vs-market comparison to a zone-vs-Europe comparison:

* calendar profiles  mean price per hour of day, weekday and month, divided by
                     the zone's annual mean so zones at different levels are
                     comparable;
* alignment rho      Pearson correlation between a zone's profile and the
                     all-zone mean profile (same peaks and troughs?);
* amplitude ratio    range of the zone's profile over the range of the
                     all-zone profile (sharper > 1, flatter < 1). The paper's
                     compression factor xi is the inverse of this ratio with
                     the market as reference;
* tails              shares of negative, near-zero (0..1 EUR/MWh) and spike
                     (> 200 EUR/MWh) hours, extremes and the mean daily spread;
* timing             cumulative negative-price hours through the year.

Solar and wind shares of generation are attached so the tails can be read
against the generation mix.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from energy_collect.comovement import MIN_ZONE_COVERAGE, _hourly_panel, _json_default
from energy_collect.config import AppConfig

log = logging.getLogger(__name__)

# Upper bound of a "near-zero" price, EUR/MWh (the paper's zero bucket).
NEAR_ZERO = 1.0
# Price above which an hour counts as a spike, EUR/MWh.
SPIKE = 200.0
# Points kept on each price duration curve.
DURATION_POINTS = 101

PROFILES: dict[str, str] = {
    "hod": "hour of day (UTC)",
    "dow": "day of week",
    "month": "month",
}
DOW_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------


def calendar_profile(panel: pd.DataFrame, by: str, *, relative: bool = True) -> pd.DataFrame:
    """Mean price per calendar group (rows) for every zone (columns).

    With ``relative`` each zone is first divided by its own annual mean, which
    is how the paper compares profiles across years with different levels.
    """
    data = panel / panel.mean() if relative else panel
    idx = data.index
    keys = {"hod": idx.hour, "dow": idx.dayofweek, "month": idx.month - 1}
    if by not in keys:
        raise ValueError(f"unknown profile {by!r}; expected one of {sorted(keys)}")
    return data.groupby(keys[by]).mean()


def alignment(profile: pd.Series | np.ndarray, reference: pd.Series | np.ndarray) -> float:
    """Pearson correlation of two profiles: 1 = same shape, <= 0 = shape missed.

    Invariant to level and scale, so a profile can be perfectly aligned yet
    strongly compressed.
    """
    a = np.asarray(profile, dtype=float)
    b = np.asarray(reference, dtype=float)
    if np.std(a) == 0 or np.std(b) == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def amplitude_ratio(profile: pd.Series | np.ndarray, reference: pd.Series | np.ndarray) -> float:
    """Range of ``profile`` over range of ``reference`` (1 = same amplitude)."""
    a = np.asarray(profile, dtype=float)
    b = np.asarray(reference, dtype=float)
    ref_range = np.nanmax(b) - np.nanmin(b)
    if ref_range == 0:
        return float("nan")
    return float((np.nanmax(a) - np.nanmin(a)) / ref_range)


def distribution_metrics(series: pd.Series) -> dict[str, Any]:
    """Level, tail and spread metrics of one hourly price series."""
    s = series.dropna()
    if s.empty:
        return {}
    daily = s.groupby(s.index.floor("D"))
    spread = (daily.max() - daily.min())
    return {
        "hours": int(len(s)),
        "mean": float(s.mean()),
        "median": float(s.median()),
        "std": float(s.std()),
        "negative_share": float((s < 0).mean()),
        "negative_hours": int((s < 0).sum()),
        "near_zero_share": float(((s >= 0) & (s <= NEAR_ZERO)).mean()),
        "spike_share": float((s > SPIKE).mean()),
        "spike_hours": int((s > SPIKE).sum()),
        "peak": float(s.max()),
        "lowest": float(s.min()),
        "daily_spread": float(spread.mean()),
        "floor_at_zero": bool(s.min() == 0.0),
    }


def cumulative_negative_hours(panel: pd.DataFrame) -> pd.DataFrame:
    """Running count of negative-price hours, sampled at the end of each day."""
    daily = (panel < 0).groupby(panel.index.floor("D")).sum()
    return daily.cumsum()


def duration_curve(series: pd.Series, points: int = DURATION_POINTS) -> list[float]:
    """Prices sorted high to low, sampled at ``points`` evenly spaced ranks."""
    s = np.sort(series.dropna().to_numpy())[::-1]
    if s.size == 0:
        return []
    idx = np.linspace(0, s.size - 1, points).round().astype(int)
    return s[idx].tolist()


def generation_shares(config: AppConfig, year: int) -> dict[str, dict[str, float]]:
    """Solar and wind shares of total reported generation per zone (percent)."""
    path = config.data_root / "processed" / "entsoe" / f"generation_{year}.parquet"
    if not path.exists():
        return {}
    gen = pd.read_parquet(path, columns=["zone", "psr_type", "value"])
    total = gen.groupby("zone")["value"].sum()
    solar = gen[gen["psr_type"] == "Solar"].groupby("zone")["value"].sum()
    wind = gen[gen["psr_type"].str.startswith("Wind")].groupby("zone")["value"].sum()
    out: dict[str, dict[str, float]] = {}
    for zone, tot in total.items():
        if tot <= 0:
            continue
        out[zone] = {
            "solar_share": float(100 * solar.get(zone, 0.0) / tot) if zone in solar else None,
            "wind_share": float(100 * wind.get(zone, 0.0) / tot) if zone in wind else None,
        }
    return out


def _spearman(x: pd.Series, y: pd.Series) -> dict[str, Any]:
    pair = pd.concat([x, y], axis=1).dropna()
    if len(pair) < 5:
        return {"rho": None, "n": int(len(pair))}
    return {"rho": float(pair.corr(method="spearman").iloc[0, 1]), "n": int(len(pair))}


# --------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------


def run_price_shape(config: AppConfig, year: int) -> dict[str, Any]:
    proc = config.data_root / "processed" / "entsoe"
    panel = _hourly_panel(pd.read_parquet(proc / f"prices_{year}.parquet"), year)
    coverage = panel.notna().mean()
    zones = sorted(coverage[coverage >= MIN_ZONE_COVERAGE].index)
    panel = panel[zones]
    log.info("price shape: %d zones x %d hours", len(zones), len(panel))

    profiles: dict[str, Any] = {}
    reference: dict[str, pd.Series] = {}
    for key in PROFILES:
        rel = calendar_profile(panel, key, relative=True)
        absolute = calendar_profile(panel, key, relative=False)
        reference[key] = rel.mean(axis=1)
        profiles[key] = {
            "label": PROFILES[key],
            "groups": {"hod": list(range(24)), "dow": DOW_LABELS, "month": MONTH_LABELS}[key],
            "relative": {z: rel[z].round(4).tolist() for z in zones},
            "absolute": {z: absolute[z].round(2).tolist() for z in zones},
            "europe_relative": reference[key].round(4).tolist(),
        }

    shares = generation_shares(config, year)
    rows: list[dict[str, Any]] = []
    hod_rel = calendar_profile(panel, "hod")
    for zone in zones:
        metrics = distribution_metrics(panel[zone])
        row: dict[str, Any] = {"zone": zone, **metrics}
        for key in PROFILES:
            prof = pd.Series(profiles[key]["relative"][zone])
            row[f"rho_{key}"] = alignment(prof, reference[key])
            row[f"amp_{key}"] = amplitude_ratio(prof, reference[key])
        row["hod_trough"] = int(hod_rel[zone].idxmin())
        row["hod_peak"] = int(hod_rel[zone].idxmax())
        row["midday_relative"] = float(hod_rel[zone].loc[10:13].mean())
        row.update(shares.get(zone, {"solar_share": None, "wind_share": None}))
        rows.append(row)
    table = pd.DataFrame(rows).set_index("zone")

    cum = cumulative_negative_hours(panel)
    allows_negative = table[~table["floor_at_zero"]]
    summary = {
        "n_zones": len(zones),
        "hours": int(len(panel)),
        "zones_with_negative": int((table["negative_hours"] > 0).sum()),
        "zones_floor_at_zero": sorted(table.index[table["floor_at_zero"]].tolist()),
        "most_negative": {
            "zone": str(table["negative_hours"].idxmax()),
            "hours": int(table["negative_hours"].max()),
        },
        "most_spikes": {
            "zone": str(table["spike_share"].idxmax()),
            "share": float(table["spike_share"].max()),
        },
        "hod_alignment_median": float(table["rho_hod"].median()),
        "hod_shape_similarity_mean": float(
            hod_rel.corr().to_numpy()[np.triu_indices(len(zones), 1)].mean()
        ),
        "negative_vs_solar": _spearman(allows_negative["negative_share"], allows_negative["solar_share"]),
        "negative_vs_wind": _spearman(allows_negative["negative_share"], allows_negative["wind_share"]),
        "midday_vs_solar": _spearman(table["midday_relative"], table["solar_share"]),
    }

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "year": year,
        "zones": zones,
        "thresholds": {"near_zero": NEAR_ZERO, "spike": SPIKE},
        "profiles": profiles,
        "metrics": [
            {k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in r.items()}
            for r in table.reset_index().to_dict(orient="records")
        ],
        "cumulative_negative": {
            "dates": [d.strftime("%Y-%m-%d") for d in cum.index],
            "series": {z: cum[z].astype(int).tolist() for z in zones},
        },
        "duration_curves": {z: [round(v, 2) for v in duration_curve(panel[z])] for z in zones},
        "summary": summary,
        "method": (
            "Hourly UTC day-ahead prices (15-min MTU averaged into hours). Calendar profiles are "
            "group means of price / annual mean; alignment = Pearson r with the unweighted all-zone "
            "mean profile; amplitude ratio = profile range / all-zone profile range. Metrics after "
            "Cäsar, Neumann & Zwickl-Bernhard (2026), adapted from model-vs-market to zone-vs-Europe."
        ),
        "reference": "Cäsar, Neumann & Zwickl-Bernhard (2026), SSRN doi:10.2139/ssrn.6714235",
    }
    report["findings"] = _findings(report, table)

    out_dir = config.data_root / "manifests"
    dash_dir = out_dir / "dashboard"
    dash_dir.mkdir(parents=True, exist_ok=True)
    path = dash_dir / f"price_shape_{year}.json"
    path.write_text(json.dumps(report, default=_json_default), encoding="utf-8")
    report["dashboard_path"] = str(path)
    return report


def _findings(report: dict[str, Any], table: pd.DataFrame) -> dict[str, str]:
    s = report["summary"]
    floor = s["zones_floor_at_zero"]
    neg_solar = s["negative_vs_solar"]
    top_negative = table["negative_hours"].nlargest(3)
    top_text = ", ".join(
        f"{z} ({int(h)} h, solar {table.at[z, 'solar_share']:.0f}%)"
        if pd.notna(table.at[z, "solar_share"]) else f"{z} ({int(h)} h)"
        for z, h in top_negative.items()
    )
    flattest = table["amp_hod"].nsmallest(3).index.tolist()
    misaligned = table["rho_hod"].nsmallest(3).index.tolist()
    return {
        "negatives": (
            f"{s['zones_with_negative']} of {s['n_zones']} zones clear below zero at least once; "
            f"{s['most_negative']['zone']} does so most often ({s['most_negative']['hours']} hours). "
            f"{len(floor)} zones never go below exactly 0 EUR/MWh ({', '.join(floor)}), so how often "
            "a zone is negative depends on market rules as well as on the generation mix."
        ),
        "solar": (
            "Among zones that allow negative prices, the share of negative hours is not ranked by "
            f"reported solar share (Spearman {neg_solar['rho']:.2f}, n = {neg_solar['n']}). The most "
            f"negative zones are {top_text}. Indicative only: ENTSO-E generation (A75) misses much "
            "distributed solar in some zones, so reported solar shares understate it."
            if neg_solar["rho"] is not None
            else "Solar shares unavailable."
        ),
        "shape": (
            f"Daily shapes are broadly shared (mean pairwise r = {s['hod_shape_similarity_mean']:.2f}), "
            f"but the flattest profiles are {', '.join(flattest)} and the least aligned with the "
            f"European shape are {', '.join(misaligned)}."
        ),
    }
