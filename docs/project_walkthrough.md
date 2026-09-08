# Project walkthrough — European energy dependency mapping

Step-by-step guide to what was collected, what it means, and how it was analysed.

---

## The big picture

**Goal:** Map how European electricity markets depend on each other — through **prices**, **physical flows**, **static grid/plants**, and (new) **directed information flow** (Transfer Entropy).

**Supervisor:** Stefan  
**Data year:** 2025  
**Geographic scope:** 45 bidding zones in `config/zones.yaml` (EU coupling region + GB, CH, NO, Balkans)

---

## Phase 1 — Data collection (ENTSO-E)

### What is ENTSO-E?

**ENTSO-E** = European Network of Transmission System Operators for Electricity.  
They run the **[Transparency Platform](https://transparency.entsoe.eu/)** — a public API where TSOs publish operational data.

### How we collect

```bash
PYTHONPATH=src python3 -m energy_collect.cli collect --year 2025
```

- Code: `src/energy_collect/collectors/entsoe.py`
- Each **zone × dataset × month** is one API job
- Progress stored in `data/manifests/collection.db` (SQLite manifest)
- Successful rows → parquet files under `data/processed/entsoe/`

### Datasets collected

| Internal name | ENTSO-E doc | Code | Meaning | Unit | Zones (2025) |
|---------------|-------------|------|---------|------|--------------|
| `day_ahead_prices` | 12.1.D | **A44** | Wholesale price for electricity delivered tomorrow | EUR/MWh | 43 |
| `actual_load` | 6.1.A | **A65** | Total consumption in the zone | MW | 44 |
| `generation_actual` | 16.1.B&C | **A75** | Generation by fuel type (PSR) | MW | 43 |
| `imbalance_prices` | 17.1.G | **A85** | Price for balancing up/down | EUR/MWh | 40 (raw) |
| `crossborder_flows` | 12.1.G | **A11** | Physical power crossing a border | MW | 44 endpoints |
| `scheduled_exchanges` | 12.1.E | A09 | Commercially scheduled trade | MW | raw only |
| `net_transfer_capacity` | 11.1 | **A61** | Max transferable capacity (NTC) | MW | partial |

**Processed parquets (main analysis inputs):**
- `prices_2025.parquet`
- `load_2025.parquet`
- `generation_2025.parquet`
- `flows_2025.parquet`

### Abbreviations glossary

| Term | Meaning |
|------|---------|
| **TSO** | Transmission System Operator (runs the grid in a country/region) |
| **Bidding zone** | Smallest market unit for day-ahead pricing (may ≠ country) |
| **DA / day-ahead** | Market where prices for tomorrow are set today |
| **EIC** | Energy Identification Code — ENTSO-E’s ID for a zone/node |
| **PSR** | Production / generation by **P**hysical **S**torage and **R**eservoir category (fuel types) |
| **MW** | Megawatt — power (flow, load, generation) |
| **MWh** | Megawatt-hour — energy (price is per MWh) |
| **NTC** | Net Transfer Capacity — max MW that can cross a border |
| **SEM** | Single Electricity Market (Ireland all-island: `IE_SEM`) |
| **DE_LU** | Combined Germany + Luxembourg bidding zone (not `DE` alone) |
| **Pearson r** | Correlation coefficient (−1 to +1); used for price coupling |
| **TE** | Transfer Entropy — directed information flow between time series (bits) |
| **HOD** | Hour-of-day seasonal pattern |
| **DOW** | Day-of-week seasonal pattern |
| **MOY** | Month-of-year seasonal pattern (captures quarterly/seasonal levels) |
| **GEM** | Global Energy Monitor — power plant database |
| **PyPSA-Eur** | Open-source European grid model (lines/substations) |
| **OSM** | OpenStreetMap — source for grid geometry |

### Why zone counts differ (43 vs 44 vs 45)

Not a bug — TSOs publish different document types unevenly:

| Missing | Dataset(s) | Reason |
|---------|------------|--------|
| **GB** | Almost all | ENTSO-E returns no 2025 data for EIC `10YGB----------A` (post-Brexit / code issue) |
| **BA** | DA prices only | Load + generation exist; no day-ahead price on platform |
| **AL** | Generation only | Prices + load OK; no A75 generation-by-fuel |
| **IT_SARD** | Flows | Island links have zero A11 rows |
| **CY** | All | `python-entsoe` does not support Cyprus |

See `data/manifests/gaps_report.json` or dashboard **Data coverage** tab.

---

## Phase 2 — Validation, graph, static layers

### Flow validation

```bash
PYTHONPATH=src python3 -m energy_collect.cli validate-flows --year 2025
```

**Problem discovered:** ENTSO-E often publishes the **same aggregate export** in both directions for a border (duplicate), instead of a true directed flow.

- 171 of 177 directed pairs flagged as `duplicate_export`
- Only **4 borders** have clearly distinct directions (e.g. PT→ES, IE_SEM→GB)
- We pick **one canonical edge per undirected border** for the graph (`select_graph_flow_edges`)

Output: `data/manifests/flow_validation_2025.json`

### Dependency graph (Pearson + flows + structure)

```bash
PYTHONPATH=src python3 -m energy_collect.cli build-graph --year 2025
```

Three edge types:

1. **Price coupling** — Pearson r ≥ 0.85 on hourly DA prices (undirected)
2. **Physical flow** — mean |MW| on canonical border edges (directed)
3. **Structural** — neighbors from `zones.yaml` (topology prior)

Output: `data/manifests/dependency_graph_2025.json`  
Stats: 45 nodes, 68 price edges, 89 flow edges, 177 structural edges

### Static grid + power plants

```bash
PYTHONPATH=src python3 -m energy_collect.cli static-gem --file "/path/to/Global Integrated Power.xlsx"
PYTHONPATH=src python3 -m energy_collect.cli merge-static --year 2025
```

- **OSM/PyPSA-Eur:** ~9,162 transmission lines, substations per country
- **GEM:** 55,720 EU power plant units across 33 countries
- Merged onto graph nodes: `dependency_graph_2025_with_static.json`

---

## Phase 3 — Seasonality, Transfer Entropy, dashboard

### Seasonality decomposition (new)

```bash
PYTHONPATH=src python3 -m energy_collect.cli decompose-seasonality --year 2025 --all
```

For each zone, remove predictable patterns **in order**:

1. **Hour-of-day** mean (intraday peak/off-peak)
2. **Day-of-week** mean (weekday vs weekend)
3. **Month-of-year** mean (winter vs summer / quarterly levels)
4. **7-day rolling trend**
5. What remains = **residual** (used for TE)

Outputs:
- `prices_deseasonalised_2025.parquet`
- `load_deseasonalised_2025.parquet`
- `data/manifests/dashboard/seasonality_prices_2025.json`
- `data/manifests/dashboard/seasonality_load_2025.json`

Dashboard **Seasonality** tab: intraday chart, quarterly bar chart, calendar-month line chart, variance breakdown table.

### Transfer Entropy (k-NN Rényi TE)

```bash
PYTHONPATH=src python3 -m energy_collect.cli compute-te --year 2025 --min-te 0.003
```

**What it measures:** Does knowing zone A’s **past prices** reduce uncertainty about zone B’s **future prices**, beyond B’s own history? → directed edge A → B.

**Method (Tabachová et al. 2026, arXiv:2601.01497):**
- k-NN **Rényi entropy** estimator (Leonenko et al., Eq. 4–6)
- **α = 1** → classical Shannon transfer entropy
- **Effective RTE (ERTE)** — shuffle bias correction (Eq. 8)
- Input: deseasonalised prices; default k=4, memory r=l=1 hour

Outputs:
- `transfer_entropy_2025.json` — edge list (~1,687 edges at min_te=0.003)
- `dependency_graph_2025_te.json` — TE graph manifest

Options: `--alpha`, `--k-neighbors`, `--method discrete` (legacy binning)

### Dashboard

```bash
PYTHONPATH=src python3 -m energy_collect.cli build-dashboard --year 2025
cd docs/dashboard && python3 -m http.server 8765
```

Tabs: Map | Prices | Seasonality | Transfer entropy | Data coverage

---

## End-to-end pipeline (copy-paste)

```bash
# Collection (once, needs ENTSOE_API_KEY in .env)
PYTHONPATH=src python3 -m energy_collect.cli collect --year 2025

# Phase 2
PYTHONPATH=src python3 -m energy_collect.cli validate-flows --year 2025
PYTHONPATH=src python3 -m energy_collect.cli build-graph --year 2025 --skip-flow-validation
PYTHONPATH=src python3 -m energy_collect.cli merge-static --year 2025

# Phase 3
PYTHONPATH=src python3 -m energy_collect.cli decompose-seasonality --year 2025 --all
PYTHONPATH=src python3 -m energy_collect.cli compute-te --year 2025 --min-te 0.003
PYTHONPATH=src python3 -m energy_collect.cli build-dashboard --year 2025
```

---

## Key findings so far

**Price coupling (Pearson):** LT↔LV, BG↔RO, ES↔PT, HR↔SI — very high correlation.

**Flows:** FR, DE_LU, NO zones dominate by mean MW; duplicate-export issue limits directed interpretation.

**Seasonality:** Southern/Balkan zones (GR, MK, RS) show strongest intraday patterns; MOY captures winter/summer price level shifts.

**Transfer entropy:** Strongest cross-border directed coupling includes RS→AT, CH→DE_LU, CH→AT (on deseasonalised residuals).

---

## What is still open

- GB data retry (`UK` / alternate EIC)
- Imbalance / NTC / scheduled exchanges in processed parquets
- PDF report updated with Phase 3 sections
- Optional: α ≠ 1 Rényi runs for price-spike / tail analysis

---

## File map

```
config/zones.yaml              # 45 zones + neighbors
data/processed/entsoe/         # Time series parquets
data/manifests/                # Graph, validation, gaps, TE, seasonality JSON
data/raw/static/gem/           # GEM power plants
docs/dashboard/                # Interactive web UI
docs/entsoe_2025_report.pdf    # Phase 1–2 report for Stefan
src/energy_collect/            # All Python modules
```

For field-level column definitions see `docs/data_dictionary.md`.
