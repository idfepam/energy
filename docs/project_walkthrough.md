# Project walkthrough — European energy dependency mapping

Step-by-step guide to what was collected, what it means, and how it was analysed.

---

## The big picture

**Goal:** Map how European electricity markets depend on each other — through **prices**, **physical flows**, **static grid/plants**, **directed information flow** (Transfer Entropy), and (new) the **co-movement structure** behind Stefan's RQ1–RQ3.

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

Tabs: Map | Prices | Seasonality | Transfer entropy | Price vs flow | TE regimes | RQ1 · Modes | RQ2 · Persistence | RQ3 · Topology | Network & grid | Data coverage

---

## Phase 4 — RQ1-RQ3 co-movement analysis

Stefan's refocused research questions (9 Sep 2026). Full write-up:
**[research_questions.md](research_questions.md)**. One command produces all three:

```bash
PYTHONPATH=src python3 -m energy_collect.cli analyze-comovement --year 2025
```

Code: `src/energy_collect/comovement.py`. Outputs `comovement_2025.json` plus the
dashboard slice, and three dashboard tabs (**RQ1 · Modes**, **RQ2 · Persistence**,
**RQ3 · Topology**).

### Panel construction (shared by all three RQs)

From 1 Oct 2025 some TSOs publish a **15-minute** market time unit while others stay
hourly, so the raw index mixes resolutions. Everything is averaged into **hourly UTC
buckets** first — 43 zones x 8,401 complete hours. Analyses run on both raw levels
and deseasonalised residuals; residuals are primary.

### RQ1 — market mode vs cluster modes

Eigen-decomposition of the zone correlation matrix. The hard part is significance:
prices are autocorrelated (mean AR(1) = 0.83), so 8,401 hours are worth only ~801
independent observations and a textbook Marchenko-Pastur bound would call almost
everything significant. Two independent tests are used and agree on **6 modes**:

1. **Phase-randomised surrogates** (500 reps) — each zone keeps its own power
   spectrum, Fourier phases are randomised, all cross-zone coupling destroyed.
2. **Marchenko-Pastur** with the AR(1)-adjusted effective sample size.

Result: market mode **47%**, five cluster modes **29%**, noise **24%**. On raw levels
the market mode reads 59% — the 12-point gap is shared calendar shape.

### RQ2 — partition persistence

Clustering runs on the **market-mode-removed** correlation matrix (modes 2..6), with
average linkage on `sqrt(2(1-C_group))`. k = 8 chosen on the silhouette curve,
excluding singleton partitions.

Each stratum (4 seasons, 4 hour blocks, 16 season x hour cells) is scored by
**Adjusted Rand Index** against the full-year partition — and against a
**permutation null of the same sample size**, because a shorter window lowers ARI on
its own. Result: persists everywhere except summer, and specifically summer daylight.

### RQ3 — co-movement vs topology

Hop distance from `zones.yaml`, Mantel permutation test, Mann-Whitney AUC for
adjacency, and border tables scored against the hop-decay curve.

**Important data note:** ENTSO-E republishes each zone's aggregate export against
every one of its borders — the same defect `flow_validation` found in A11 flows is
also present in A61 NTC (FR reports 2,801 MW on BE, DE_LU and IT_NORTH alike). Those
values are excluded, leaving **37 of 108** NTC borders and **2 of 177** directed flow
pairs usable. Correlation, convergence and spread come from the price panel and are
unaffected.

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

# Phase 4 (RQ1-RQ3)
PYTHONPATH=src python3 -m energy_collect.cli analyze-comovement --year 2025

PYTHONPATH=src python3 -m energy_collect.cli build-dashboard --year 2025
```

---

## Key findings so far

**Price coupling (Pearson):** LT↔LV, BG↔RO, ES↔PT, HR↔SI — very high correlation.

**Flows:** FR, DE_LU, NO zones dominate by mean MW; duplicate-export issue limits directed interpretation.

**Seasonality:** Southern/Balkan zones (GR, MK, RS) show strongest intraday patterns; MOY captures winter/summer price level shifts.

**Transfer entropy:** Strongest cross-border directed coupling includes RS→AT, CH→DE_LU, CH→AT (on deseasonalised residuals).

**RQ1 — co-movement structure:** one Europe-wide mode (47% of variance, all loadings positive) plus **5** statistically supported cluster dimensions (29%); 24% noise. On raw levels the common mode reads 59% — 12 points of that is shared calendar, not shared shocks.

**RQ2 — persistence:** the 8-bloc partition (Balkans+SE, CWE/CEE core, Italy+CH, Baltics, Iberia+FR, Nordic north, North Sea, Nordic south+Atlantic) holds in every season and hour block. Only **summer daylight** reorganises, and there the Europe-wide mode itself drops from 56% (night) to 32%. Iberia and the Baltics never move; DE_LU, AT, PL, SK and IE_SEM sit on the moving boundary.

**RQ3 — topology:** correlation decays monotonically with hop distance (0.82 → 0.10); adjacency AUC 0.87, Mantel r 0.60. A direct line is neither sufficient (FI–NO_4 r=0.32, NO_1–NO_3 converges 1.2% of hours) nor necessary (HR–RO r=0.96 at two hops).

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
src/energy_collect/comovement.py  # RQ1-RQ3 analysis
docs/research_questions.md     # RQ1-RQ3 findings
```

For field-level column definitions see `docs/data_dictionary.md`.
