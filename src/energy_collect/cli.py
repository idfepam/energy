from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv

from energy_collect.collectors.entsoe import ENTSOECollector
from energy_collect.collectors.static.gem import GEMCollector
from energy_collect.collectors.static.osm_grid import OSMGridCollector
from energy_collect.config import load_config
from energy_collect.storage.manifest import Manifest
from energy_collect.validate import consolidate_processed, validate_collection
from energy_collect.flow_validation import run_flow_validation
from energy_collect.graph import build_dependency_graph, write_dependency_graph
from energy_collect.static_merge import merge_static_layers
from energy_collect.seasonality import run_seasonality_decomposition, run_all_seasonality
from energy_collect.transfer_entropy import run_transfer_entropy
from energy_collect.dashboard import build_dashboard_bundle
from energy_collect.meeting_analyses import DEFAULT_NESTED_ZONES, run_meeting_analyses

app = typer.Typer(help="European energy data collection framework")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def _parse_csv(value: Optional[str]) -> list[str] | None:
    if not value:
        return None
    return [v.strip() for v in value.split(",") if v.strip()]


@app.command("entsoe")
def collect_entsoe(
    year: int = typer.Option(2025, help="Collection year"),
    start: Optional[str] = typer.Option(None, help="Override start date YYYY-MM-DD"),
    end: Optional[str] = typer.Option(None, help="Override end date YYYY-MM-DD"),
    zones: Optional[str] = typer.Option(None, help="Comma-separated zone codes"),
    datasets: Optional[str] = typer.Option(None, help="Comma-separated dataset names"),
    all_zones: bool = typer.Option(False, help="Use all configured bidding zones"),
    resume: bool = typer.Option(True, help="Skip already successful jobs"),
    dry_run: bool = typer.Option(False, help="Plan jobs without fetching"),
    retry_failed: bool = typer.Option(False, help="Retry only failed jobs"),
) -> None:
    """Collect ENTSO-E transparency data."""
    load_dotenv()
    config = load_config()
    manifest = Manifest(config.data_root / "manifests" / "collection.db")
    collector = ENTSOECollector(config, manifest)

    zone_list = None if all_zones or not zones else _parse_csv(zones)
    dataset_list = _parse_csv(datasets)

    if start and end:
        # Short-window mode: override year planning with custom jobs
        from energy_collect.collectors.base import CollectionJob

        selected_datasets = dataset_list or list(config.datasets.keys())
        selected_zones = zone_list or ["FR", "DE_LU"]
        jobs = []
        for ds_name in selected_datasets:
            ds = config.datasets[ds_name]
            if ds["scope"] == "zone":
                for zone in selected_zones:
                    jobs.append(
                        CollectionJob(
                            dataset=ds_name,
                            scope_key=zone,
                            period_start=start,
                            period_end=end,
                            params={"zone": zone},
                        )
                    )
            else:
                from energy_collect.utils.zones import border_pairs

                pairs = border_pairs(config.zones)
                for pair in pairs:
                    if pair.from_zone in selected_zones or pair.to_zone in selected_zones:
                        jobs.append(
                            CollectionJob(
                                dataset=ds_name,
                                scope_key=f"{pair.from_zone}>{pair.to_zone}",
                                period_start=start,
                                period_end=end,
                                params={
                                    "from_zone": pair.from_zone,
                                    "to_zone": pair.to_zone,
                                },
                            )
                        )
        if dry_run:
            typer.echo(f"Dry run: {len(jobs)} jobs planned")
            return
        stats = {"planned": len(jobs), "success": 0, "failed": 0, "skipped": 0}
        for job in jobs:
            job_id = Manifest.make_job_id(
                job.dataset, job.scope_key, job.period_start, job.period_end
            )
            if collector.manifest.should_skip(job_id, resume):
                stats["skipped"] += 1
                continue
            try:
                row_count, file_path = collector.run_job(job)
                collector.manifest.upsert(
                    job_id=job_id,
                    dataset=job.dataset,
                    scope_key=job.scope_key,
                    period_start=job.period_start,
                    period_end=job.period_end,
                    status="success",
                    row_count=row_count,
                    file_path=file_path,
                )
                stats["success"] += 1
            except Exception as exc:
                collector.manifest.upsert(
                    job_id=job_id,
                    dataset=job.dataset,
                    scope_key=job.scope_key,
                    period_start=job.period_start,
                    period_end=job.period_end,
                    status="failed",
                    error=str(exc),
                )
                stats["failed"] += 1
                typer.echo(f"Failed {job.dataset} {job.scope_key}: {exc}")
        typer.echo(str(stats))
        return

    stats = collector.collect(
        datasets=dataset_list,
        zones=zone_list,
        year=year,
        resume=resume,
        dry_run=dry_run,
        retry_failed=retry_failed,
    )
    typer.echo(str(stats))


@app.command("validate")
def validate(
    year: int = typer.Option(2025, help="Year to validate"),
    consolidate: bool = typer.Option(True, help="Build processed parquet files"),
) -> None:
    """Validate collected data and optionally consolidate processed files."""
    load_dotenv()
    config = load_config()
    report = validate_collection(config, year)
    typer.echo(f"Manifest summary: {report['manifest_summary']}")
    for ds, info in report["datasets"].items():
        typer.echo(f"  {ds}: {info['files']} files, {info['total_rows']} rows")
        if info["issues"]:
            typer.echo(f"    issues: {info['issues'][:3]}")
    if consolidate:
        consolidate_processed(config, year)
        typer.echo("Processed files written to data/processed/entsoe/")


@app.command("static-osm")
def collect_static_osm() -> None:
    """Download PyPSA-Eur OSM transmission grid from Zenodo."""
    load_dotenv()
    config = load_config()
    collector = OSMGridCollector(config)
    out = collector.collect()
    typer.echo(f"Saved to {out}")


@app.command("static-gem")
def collect_static_gem(
    url: str | None = typer.Option(None, help="Direct URL to GEM GIPT XLSX export"),
    file: str | None = typer.Option(None, "--file", help="Local path to GIPT XLSX file"),
) -> None:
    """Import Global Energy Monitor power plant data."""
    if not url and not file:
        typer.echo("Provide --file or --url", err=True)
        raise typer.Exit(1)
    if url and file:
        typer.echo("Use only one of --file or --url", err=True)
        raise typer.Exit(1)
    load_dotenv()
    config = load_config()
    collector = GEMCollector(config)
    out = collector.collect(xlsx_url=url, xlsx_file=file)
    typer.echo(f"Saved to {out}")


@app.command("validate-flows")
def validate_flows_cmd(
    year: int = typer.Option(2025, help="Year to validate"),
) -> None:
    """Validate cross-border physical flows per directed border pair."""
    load_dotenv()
    config = load_config()
    report = run_flow_validation(config, year)
    typer.echo(f"Flow validation written to {report['output_path']}")
    typer.echo(f"By status: {report['by_status']}")
    dup = report.get("duplicate_exporters", {})
    if dup:
        typer.echo("Duplicate aggregate exporters:")
        for zone, targets in sorted(dup.items()):
            typer.echo(f"  {zone}: {len(targets)} borders flagged")


@app.command("build-graph")
def build_graph_cmd(
    year: int = typer.Option(2025, help="Year for graph"),
    price_min_r: float = typer.Option(0.85, help="Min |Pearson r| for price edges"),
    skip_flow_validation: bool = typer.Option(False, help="Reuse existing flow_validation JSON"),
) -> None:
    """Build dependency graph from validated flows + price coupling."""
    load_dotenv()
    config = load_config()
    flow_val = None
    if skip_flow_validation:
        p = config.data_root / "manifests" / f"flow_validation_{year}.json"
        if p.exists():
            flow_val = __import__("json").loads(p.read_text())
    out = write_dependency_graph(
        config, year, price_min_r=price_min_r, flow_validation=flow_val
    )
    graph = __import__("json").loads(out.read_text())
    typer.echo(f"Dependency graph written to {out}")
    typer.echo(f"Stats: {graph['stats']}")


@app.command("merge-static")
def merge_static_cmd(
    year: int = typer.Option(2025, help="Graph year to enrich"),
) -> None:
    """Attach PyPSA-Eur / GEM static attributes to dependency graph nodes."""
    load_dotenv()
    config = load_config()
    result = merge_static_layers(config, year)
    typer.echo(f"Merged graph written to {result['output_path']}")
    typer.echo(f"Grid lines: {result['grid_lines']}, GEM countries: {result['gem_countries']}")


@app.command("decompose-seasonality")
def decompose_seasonality_cmd(
    year: int = typer.Option(2025, help="Year"),
    dataset: str = typer.Option("prices", help="Dataset: prices or load"),
    all_datasets: bool = typer.Option(False, "--all", help="Decompose both prices and load"),
) -> None:
    """Decompose seasonality (intraday, weekly, monthly/quarterly) and write residuals."""
    load_dotenv()
    config = load_config()
    if all_datasets:
        results = run_all_seasonality(config, year)
        for name, report in results.items():
            typer.echo(f"{name}: {report['zones']} zones → {report['output_path']}")
        return
    report = run_seasonality_decomposition(config, year, dataset=dataset)
    typer.echo(f"Seasonality written to {report['output_path']}")
    typer.echo(f"Zones: {report['zones']}, residual: {report['residual_file']}")
    top_moy = report.get("top_moy_strength", [])[:3]
    if top_moy:
        typer.echo("Strongest month-of-year pattern:")
        for r in top_moy:
            typer.echo(f"  {r['zone']}: moy={r['moy_strength']}, quarter spread={r['quarter_spread']} {report.get('unit','')}")


@app.command("compute-te")
def compute_te_cmd(
    year: int = typer.Option(2025, help="Year"),
    min_te: float = typer.Option(0.005, help="Minimum TE threshold (bits)"),
    neighbor_only: bool = typer.Option(False, help="Only border pairs from zones.yaml"),
    raw_prices: bool = typer.Option(False, help="Use raw prices instead of deseasonalised"),
    method: str = typer.Option("knn", help="Estimator: knn (Rényi k-NN) or discrete"),
    alpha: float = typer.Option(1.0, help="Rényi order α (1 = Shannon TE)"),
    k_neighbors: int = typer.Option(4, help="k-NN neighbours (paper: k=4–10)"),
    memory_r: int = typer.Option(1, help="Target memory length r"),
    memory_l: int = typer.Option(1, help="Source memory length l"),
    effective: bool = typer.Option(True, help="Effective RTE with shuffle bias correction"),
    n_bins: int = typer.Option(8, help="Bins for discrete method only"),
) -> None:
    """Compute directed Rényi Transfer Entropy (k-NN) on price series."""
    load_dotenv()
    config = load_config()
    est: str = "knn" if method == "knn" else "discrete"
    report = run_transfer_entropy(
        config,
        year,
        use_deseasonalised=not raw_prices,
        min_te=min_te,
        neighbor_only=neighbor_only,
        method=est,  # type: ignore[arg-type]
        k=k_neighbors,
        alpha=alpha,
        r=memory_r,
        l=memory_l,
        effective=effective,
        n_bins=n_bins,
    )
    typer.echo(f"TE report written to {report['output_path']}")
    typer.echo(f"Graph manifest: {report.get('graph_path')}")
    typer.echo(f"Method: {report['method']}")
    typer.echo(f"Edges: {report['edge_count']}")
    for e in report.get("top_edges", [])[:5]:
        typer.echo(f"  {e['from']} -> {e['to']}: TE={e['te']}")


@app.command("analyze-meeting")
def analyze_meeting_cmd(
    year: int = typer.Option(2025, help="Year"),
    zones: Optional[str] = typer.Option(
        None,
        help="Comma-separated zones for nested Year→Month→Week→HOD TE "
        f"(default: {','.join(DEFAULT_NESTED_ZONES)})",
    ),
    n_bins: int = typer.Option(6, help="Quantile bins for discrete TE"),
) -> None:
    """Run the five coordinator meeting analyses (TE regimes, mismatch, nested TE, network, grid)."""
    load_dotenv()
    config = load_config()
    nested = _parse_csv(zones)
    report = run_meeting_analyses(config, year, nested_zones=nested, n_bins=n_bins)
    typer.echo(f"Written: {report['output_path']}")
    typer.echo(f"Dashboard JSON: {report.get('dashboard_path')}")
    mm = report["price_flow_mismatch"]
    typer.echo(f"Mismatch borders: {mm['n_borders']}  counts={mm['counts']}")
    if mm.get("fr_es"):
        e = mm["fr_es"]
        typer.echo(
            f"FR–ES: |MW|={e['mean_abs_mw']}  r={e['pearson_r']}  TE_max={e['te_max']}  class={e['class']}"
        )
    for regime, payload in report["te_regimes"].items():
        typer.echo(f"  TE {regime}: {payload['reversal_count']} reversing pairs")
    nested_rep = report["nested_te"]
    typer.echo(
        f"Nested TE zones={nested_rep['zones']}  year/month leader agreement="
        f"{nested_rep['leader_agreement_year_vs_month_avg']}/{nested_rep['pair_count']}"
    )
    grid = report["grid_network"]
    typer.echo(
        f"Grid: {grid['osm_lines']} lines, {grid['osm_substations']} substations, "
        f"{grid['osm_hvdc_links']} HVDC links"
    )


@app.command("build-dashboard")
def build_dashboard_cmd(
    year: int = typer.Option(2025, help="Year"),
) -> None:
    """Build web dashboard data bundle and open docs/dashboard/index.html."""
    load_dotenv()
    config = load_config()
    bundle = build_dashboard_bundle(config, year)
    typer.echo(f"Dashboard data: {bundle['output_js']}")
    typer.echo(f"Open: docs/dashboard/index.html (serve with: cd docs/dashboard && python3 -m http.server 8765)")


@app.command("status")
def status(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show skipped/no-data details"),
) -> None:
    """Show collection manifest summary."""
    load_dotenv()
    config = load_config()
    manifest = Manifest(config.data_root / "manifests" / "collection.db")
    summary = manifest.summary()
    total = sum(summary.values())
    typer.echo(f"Job status ({total} total): {summary}")

    skipped = summary.get("skipped", 0)
    failed = summary.get("failed", 0)
    success = summary.get("success", 0)
    if skipped:
        typer.echo(f"\nSkipped (no data / unsupported): {skipped} jobs — run `energy-collect warnings` for details")
    if failed:
        typer.echo(f"\nFailed: {failed} jobs")

    if verbose or skipped or failed:
        report = manifest.gaps_report()
        if report["full_year_gaps"]:
            typer.echo("\n--- Full-year gaps (entire zone/pair missing) ---")
            for ds, scopes in report["full_year_gaps"].items():
                typer.echo(f"  {ds}: {', '.join(scopes)}")
        if report["partial_gaps_sample"]:
            typer.echo("\n--- Partial gaps (sample) ---")
            for ds, items in report["partial_gaps_sample"].items():
                typer.echo(f"  {ds}:")
                for item in items[:8]:
                    typer.echo(f"    {item}")
        if report["failed"]:
            typer.echo("\n--- Failed ---")
            for job in report["failed"]:
                typer.echo(f"  {job['dataset']} | {job['scope_key']}: {job['error'][:100]}")


@app.command("warnings")
def warnings(
    output: Optional[str] = typer.Option(
        None, help="Write JSON report to path (default: data/manifests/gaps_report.json)"
    ),
) -> None:
    """Report all no-data skips and failures from collection."""
    load_dotenv()
    config = load_config()
    manifest = Manifest(config.data_root / "manifests" / "collection.db")
    report = manifest.gaps_report()
    report["generated_at"] = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc
    ).isoformat()

    out_path = Path(output) if output else config.data_root / "manifests" / "gaps_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(__import__("json").dumps(report, indent=2))
    typer.echo(f"Gaps report written to {out_path}")
    typer.echo(f"Summary: {report['summary']}")
    typer.echo(f"Skipped by dataset: {report['skipped_by_dataset']}")
    if report["full_year_gaps"]:
        typer.echo("\nFull-year gaps:")
        for ds, scopes in report["full_year_gaps"].items():
            typer.echo(f"  {ds}: {', '.join(scopes)}")


if __name__ == "__main__":
    app()
