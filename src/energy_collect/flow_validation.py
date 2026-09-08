"""Per-border validation of ENTSO-E cross-border physical flows."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from energy_collect.config import AppConfig
from energy_collect.utils.zones import BorderPair, border_pairs

EXPECTED_HOURS = 8784  # non-leap year hourly
DUPLICATE_FRAC = 0.95
WEAK_MIRROR_CORR = 0.5
MIN_COVERAGE = 0.90


@dataclass
class PairValidation:
    from_zone: str
    to_zone: str
    status: str
    mean_mw: float
    mean_abs_mw: float
    hours: int
    coverage: float
    duplicate_of: str | None = None
    mirror_corr: float | None = None
    notes: str = ""


def _pair_frame(flows: pd.DataFrame, from_zone: str, to_zone: str) -> pd.Series:
    mask = (flows["from_zone"] == from_zone) & (flows["to_zone"] == to_zone)
    sub = flows.loc[mask, ["timestamp", "value"]].drop_duplicates("timestamp")
    return sub.set_index("timestamp")["value"].sort_index()


def _build_exporter_wide(flows: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """One wide matrix per exporting zone (timestamp x to_zone)."""
    wide: dict[str, pd.DataFrame] = {}
    for from_zone, grp in flows.groupby("from_zone"):
        mat = grp.pivot_table(index="timestamp", columns="to_zone", values="value", aggfunc="mean")
        if not mat.empty:
            wide[from_zone] = mat
    return wide


def _max_duplicate_fraction(wide: pd.DataFrame, col: str) -> tuple[float, str | None]:
    if col not in wide.columns:
        return 1.0, None
    base = wide[col]
    worst = 0.0
    worst_other: str | None = None
    for other in wide.columns:
        if other == col:
            continue
        aligned = pd.concat([base, wide[other]], axis=1, join="inner").dropna()
        if aligned.empty:
            continue
        same = np.isclose(aligned.iloc[:, 0], aligned.iloc[:, 1], rtol=0, atol=1.0).mean()
        if same > worst:
            worst = float(same)
            worst_other = other
    return worst, worst_other


def _mirror_corr(a: pd.Series, b: pd.Series) -> float | None:
    aligned = pd.concat([a, b], axis=1, join="inner").dropna()
    if len(aligned) < 24:
        return None
    if aligned.iloc[:, 0].std() == 0 or aligned.iloc[:, 1].std() == 0:
        return None
    return float(aligned.iloc[:, 0].corr(-aligned.iloc[:, 1]))


def validate_flows(
    flows: pd.DataFrame,
    expected_pairs: list[BorderPair],
) -> list[PairValidation]:
    flows = flows.copy()
    flows["timestamp"] = pd.to_datetime(flows["timestamp"], utc=True)

    present = {
        (row.from_zone, row.to_zone)
        for row in flows[["from_zone", "to_zone"]].drop_duplicates().itertuples(index=False)
    }

    exporter_wide = _build_exporter_wide(flows)

    results: list[PairValidation] = []

    for pair in expected_pairs:
        key = (pair.from_zone, pair.to_zone)
        if key not in present:
            results.append(
                PairValidation(
                    from_zone=pair.from_zone,
                    to_zone=pair.to_zone,
                    status="missing",
                    mean_mw=0.0,
                    mean_abs_mw=0.0,
                    hours=0,
                    coverage=0.0,
                    notes="No rows in processed flows parquet",
                )
            )
            continue

        s = _pair_frame(flows, pair.from_zone, pair.to_zone)
        hours = int(s.notna().sum())
        coverage = hours / EXPECTED_HOURS
        mean_mw = float(s.mean())
        mean_abs = float(s.abs().mean())

        dup_frac, dup_of = 0.0, None
        wide = exporter_wide.get(pair.from_zone)
        if wide is not None and pair.to_zone in wide.columns:
            dup_frac, dup_of = _max_duplicate_fraction(wide, pair.to_zone)

        reverse = _pair_frame(flows, pair.to_zone, pair.from_zone)
        mirror = _mirror_corr(s, reverse) if not reverse.empty else None

        if dup_frac >= DUPLICATE_FRAC:
            status = "duplicate_export"
            notes = f">{dup_frac:.0%} identical to {pair.from_zone}>{dup_of}"
        elif hours >= 720 and coverage < MIN_COVERAGE:
            status = "partial"
            notes = f"Coverage {coverage:.1%} (< {MIN_COVERAGE:.0%})"
        elif mirror is not None and mirror < WEAK_MIRROR_CORR:
            status = "weak_mirror"
            notes = f"Reverse pair mirror corr={mirror:.2f} (< {WEAK_MIRROR_CORR})"
        else:
            status = "ok"
            notes = "Usable as directed border flow"

        results.append(
            PairValidation(
                from_zone=pair.from_zone,
                to_zone=pair.to_zone,
                status=status,
                mean_mw=round(mean_mw, 1),
                mean_abs_mw=round(mean_abs, 1),
                hours=hours,
                coverage=round(coverage, 3),
                duplicate_of=dup_of,
                mirror_corr=round(mirror, 3) if mirror is not None else None,
                notes=notes,
            )
        )

    return results


def select_graph_flow_edges(
    results: list[PairValidation],
    flows: pd.DataFrame,
) -> list[dict[str, Any]]:
    """Pick one directed edge per undirected border for the dependency graph."""
    status_rank = {"ok": 4, "partial": 3, "weak_mirror": 2, "duplicate_export": 1}
    by_key = {(r.from_zone, r.to_zone): r for r in results}
    exporter_wide = _build_exporter_wide(flows)
    seen: set[tuple[str, str]] = set()
    edges: list[dict[str, Any]] = []

    undirected: set[tuple[str, str]] = set()
    for r in results:
        undirected.add(tuple(sorted((r.from_zone, r.to_zone))))

    for a, b in sorted(undirected):
        candidates: list[tuple[int, float, PairValidation, str]] = []
        for cand, label in ((by_key.get((a, b)), f"{a}>{b}"), (by_key.get((b, a)), f"{b}>{a}")):
            if not cand or cand.status == "missing":
                continue
            rank = status_rank.get(cand.status, 0)
            dup_frac = 1.0
            w = exporter_wide.get(cand.from_zone)
            if w is not None and cand.to_zone in w.columns:
                dup_frac, _ = _max_duplicate_fraction(w, cand.to_zone)
            candidates.append((rank, -dup_frac, cand, label))

        if not candidates:
            continue

        candidates.sort(key=lambda x: (x[0], x[1], x[3]), reverse=True)
        chosen, direction = candidates[0][2], candidates[0][3]
        u = tuple(sorted((chosen.from_zone, chosen.to_zone)))
        if u in seen:
            continue
        seen.add(u)

        edge_type = "physical_flow"
        if chosen.status == "duplicate_export":
            edge_type = "physical_flow_canonical"
        elif direction != f"{chosen.from_zone}>{chosen.to_zone}":
            edge_type = "physical_flow_reverse"

        edges.append(
            {
                "from": chosen.from_zone,
                "to": chosen.to_zone,
                "mw": chosen.mean_abs_mw,
                "mean_mw": chosen.mean_mw,
                "direction_note": direction,
                "validation_status": chosen.status,
                "edge_type": edge_type,
            }
        )

    edges.sort(key=lambda e: -e["mw"])
    return edges


def validation_report(results: list[PairValidation], flows: pd.DataFrame | None = None) -> dict[str, Any]:
    by_status: dict[str, int] = {}
    for r in results:
        by_status[r.status] = by_status.get(r.status, 0) + 1

    duplicate_exporters: dict[str, list[str]] = {}
    for r in results:
        if r.status == "duplicate_export":
            duplicate_exporters.setdefault(r.from_zone, []).append(r.to_zone)

    graph_edges: list[dict[str, Any]] = []
    if flows is not None:
        graph_edges = select_graph_flow_edges(results, flows)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pairs_total": len(results),
        "by_status": by_status,
        "validated_pairs": [asdict(r) for r in results if r.status == "ok"],
        "graph_flow_edges": graph_edges,
        "graph_flow_edge_count": len(graph_edges),
        "duplicate_exporters": duplicate_exporters,
        "all_pairs": [asdict(r) for r in results],
    }


def run_flow_validation(config: AppConfig, year: int) -> dict[str, Any]:
    flows_path = config.data_root / "processed" / "entsoe" / f"flows_{year}.parquet"
    if not flows_path.exists():
        raise FileNotFoundError(
            f"Missing {flows_path}. Run: energy-collect validate --year {year}"
        )

    flows = pd.read_parquet(flows_path)
    expected = border_pairs(config.zones)
    results = validate_flows(flows, expected)
    report = validation_report(results, flows)

    out = config.data_root / "manifests" / f"flow_validation_{year}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["output_path"] = str(out)
    return report


def validated_flow_edges(report: dict[str, Any]) -> list[dict[str, Any]]:
    if report.get("graph_flow_edges"):
        return report["graph_flow_edges"]
    return [
        {
            "from": p["from_zone"],
            "to": p["to_zone"],
            "mw": p["mean_abs_mw"],
            "mean_mw": p["mean_mw"],
        }
        for p in report.get("validated_pairs", [])
    ]
