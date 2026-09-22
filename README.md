# Data-Driven Dependency Mapping of European Energy Infrastructure

Collection framework for ENTSO-E transparency data and upstream static infrastructure sources (Global Energy Monitor, OpenStreetMap/PyPSA-Eur).

**Live dashboard:** [https://idfepam.github.io/energy/](https://idfepam.github.io/energy/)

The GitHub **repository** page shows this README. The **Pages site** is the interactive dashboard (map, prices, TE, mismatch, network).

**Supervisor:** Stefan

## Setup

```bash
cd /Users/purple/Desktop/Research/energy
python3 -m pip install -e ".[dev]"
cp .env.example .env   # add your ENTSOE_API_KEY
```

Register for a free API token at [transparency.entsoe.eu](https://transparency.entsoe.eu/), then email transparency@entsoe.eu with subject "Restful API access".

## Quick test (3 days, 2 zones)

```bash
energy-collect entsoe --start 2025-01-01 --end 2025-01-04 --zones FR,DE_LU --datasets day_ahead_prices,actual_load
```

## Full 2025 EU collection

```bash
energy-collect entsoe --year 2025 --all-zones --resume
energy-collect validate --year 2025
```

Or use the helper script:

```bash
bash scripts/collect_entsoe_2025.sh
```

## Datasets collected

| Dataset | Source | Scope |
|---------|--------|-------|
| Day-ahead prices | ENTSO-E A44 | Bidding zone |
| Actual load | ENTSO-E A65 | Bidding zone |
| Generation by type | ENTSO-E A75 | Bidding zone |
| Cross-border flows | ENTSO-E A11 | Border pair |
| Scheduled exchanges | ENTSO-E A09 | Border pair |
| Net transfer capacity | ENTSO-E A61 | Border pair |
| Imbalance prices | ENTSO-E A85 | Bidding zone |

## Static infrastructure (OpenGridWorks upstream sources)

OpenGridWorks is **not** scraped directly. Instead:

```bash
# European transmission grid (OSM via PyPSA-Eur Zenodo)
energy-collect static-osm

# Power plants (requires direct GEM download URL)
energy-collect static-gem --url "https://..."
```

Get the latest GEM URL from [Global Integrated Power Tracker](https://globalenergymonitor.org/projects/global-integrated-power-tracker/download-data/).

## Data layout

```
data/
├── raw/entsoe/{dataset}/{zone}/{period}.parquet
├── raw/static/{gem,osm_grid}/
├── processed/entsoe/{prices,flows,load,generation}_2025.parquet
├── processed/static/grid_edges.parquet
└── manifests/collection.db
```

## OpenGridWorks source mapping

| OpenGridWorks layer | Collect from |
|---------------------|--------------|
| Power plants (EU) | Global Energy Monitor GIPT |
| Transmission / substations | PyPSA-Eur OSM grid (Zenodo) |
| Price overlays | ENTSO-E (this framework) |
| US layers (EIA, HIFLD) | Out of scope for EU project |

## Research questions (RQ1–RQ3)

**→ [Short answers with figures and sources](docs/ANSWERS.md)** — start here.
Full method and tables: [docs/research_questions.md](docs/research_questions.md).
Interactive: the **Answers** tab on the [dashboard](https://idfepam.github.io/energy/),
with **RQ1 · Modes**, **RQ2 · Persistence** and **RQ3 · Topology** behind it.

```bash
PYTHONPATH=src python3 -m energy_collect.cli analyze-comovement --year 2025
python3 scripts/build_rq_figures.py --year 2025
```

| | Question | Answer in one line |
|---|---|---|
| **RQ1** | One Europe-wide mode, cluster modes, how many supported? | One market mode (47% of variance, all loadings same sign) + **5** supported cluster dimensions (29%); 24% noise. Surrogate null and AR(1)-adjusted Marchenko–Pastur agree on 6 modes. |
| **RQ2** | Do clusters persist across seasons and intraday? | The 8-bloc partition persists in every season and hour block. Only summer daylight reorganises — and there the Europe-wide mode itself drops from 56% (night) to 32%. |
| **RQ3** | Does co-movement follow physical topology? | Closely but not exactly (AUC 0.87, Mantel r 0.60). A line is neither sufficient (congested Nordic/HVDC borders) nor necessary (coupled blocs two hops apart). |

## Documentation

- **[RQ1–RQ3 answers](docs/ANSWERS.md)** — the three answers, each with its figure and the source of every number
- **[RQ1–RQ3 findings](docs/research_questions.md)** — full method, tables and caveats
- **[Data dictionary](docs/data_dictionary.md)** — all zone codes, field names, PSR fuel types, units
- **[ENTSO-E data guide](docs/entsoe_data_guide.md)** — collection strategy and analysis notes
- **[Status for Stefan](docs/status_for_stefan.md)** — project progress summary

Build geographic reference tables (zone → country → lat/lon):

```bash
python3 scripts/build_geo_reference.py
```

- ENTSO-E data: subject to ENTSO-E Transparency Platform terms
- GEM data: attribute Global Energy Monitor on reuse
- OSM/PyPSA-Eur grid: ODbL 1.0
