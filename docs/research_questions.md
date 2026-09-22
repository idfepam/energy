# RQ1–RQ3 — European price co-movement, 2025

Answers to the three research questions agreed with Stefan on 9 September 2026.

**Reproduce everything below with one command:**

```bash
PYTHONPATH=src python3 -m energy_collect.cli analyze-comovement --year 2025
```

Outputs: `data/manifests/comovement_2025.json` (full) and
`data/manifests/dashboard/comovement_2025.json` (dashboard slice).
Implementation: [`src/energy_collect/comovement.py`](../src/energy_collect/comovement.py).
Interactive version: **RQ1 · Modes**, **RQ2 · Persistence**, **RQ3 · Topology** tabs on
[the dashboard](https://idfepam.github.io/energy/).

---

## The panel

| | |
|---|---|
| Zones | **43** bidding zones with day-ahead prices |
| Observations | **8,401** complete hours of 2025 |
| Resolution | hourly UTC means |
| Zones dropped | none — all 43 clear the 90% coverage bar |

Two methodological points matter before any number below.

**Resolution.** From 1 October 2025 several TSOs moved to a 15-minute market time
unit while others stayed hourly, so the raw index mixes resolutions. Everything is
averaged into hourly buckets first; without that step the zones are not comparable
and the correlation matrix is meaningless.

**Two versions of every series.** Results are reported on *raw levels* and on
*deseasonalised residuals* (hour-of-day, day-of-week, month-of-year and a 7-day
trend removed by the existing `seasonality` module). The difference between them is
itself a finding — see RQ1. Residuals are the primary series: they measure shared
*shocks*, not a shared calendar.

---

## RQ1 — How much is one Europe-wide mode, how much is cluster-specific, and how many cluster dimensions are supported?

### Answer

**One Europe-wide mode carries 47% of the variance. Five cluster dimensions are
statistically supported and carry a further 29%. The remaining 24% is noise.**

| Component | Deseasonalised (shocks) | Raw levels |
|---|---|---|
| Europe-wide mode (λ₁/N) | **47.3%** | 59.2% |
| Cluster modes (λ₂…λ_k) | **28.8%** | 16.3% |
| Noise bulk | 23.9% | 24.6% |
| Supported modes | **6** (1 market + 5 cluster) | 3 |

**About 12 percentage points of apparent Europe-wide co-movement is shared calendar
shape, not shared shocks.** Correlating raw price levels counts the common European
daily and seasonal profile as if it were market integration. This is the single
biggest reason to deseasonalise before making any co-movement claim.

### The supported modes

| Mode | Variance | What it is | Heaviest loadings |
|---|---|---|---|
| 1 | 47.3% | **Europe-wide market mode** — every loading positive | HR +0.20, CZ +0.20, HU +0.20, SI +0.19, NL +0.19, SK +0.19 |
| 2 | 9.2% | Nordic | SE_1 +0.35, SE_2 +0.34, NO_3 +0.28, FI +0.27, NO_5 +0.25 |
| 3 | 6.1% | Italian zones | IT_SUD +0.35, IT_SARD +0.33, IT_CSUD +0.33, IT_NORTH +0.32 |
| 4 | 4.9% | Iberia + France vs Nordic | ES +0.49, PT +0.49, FR +0.35, SE_1 −0.20, SE_2 −0.20 |
| 5 | 4.7% | Baltics vs Nordic | LV +0.35, LT +0.35, EE +0.35, NO_3 −0.30, NO_4 −0.26 |
| 6 | 3.9% | Iberia + Baltics vs Nordic-south | PT +0.40, ES +0.39, EE +0.29, LV +0.28, NO_1 −0.22 |

Mode 1 is a genuine market mode in the strict sense: **all 43 loadings share the same
sign**, so it is a single factor that moves every zone together, not a contrast
between two groups. Every later mode changes sign and therefore separates blocs.

### How "statistically supported" was decided

The naive Marchenko–Pastur bound is not usable here. Electricity prices are strongly
autocorrelated (mean AR(1) = 0.83 on residuals), so 8,401 hours are worth only about
**801 independent observations**. The bound moves from 1.15 to **1.52** once that is
accounted for — a difference that changes the answer.

Two independent tests were run and they agree:

1. **Phase-randomised surrogates** (500 replications). Each surrogate keeps every
   zone's own power spectrum — hence its autocorrelation — and randomises Fourier
   phases, destroying all cross-zone coupling. An eigenvalue counts only if it
   exceeds the 95th percentile of its own order statistic in that null.
2. **Marchenko–Pastur** with the AR(1)-adjusted effective sample size.

| λ | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| Observed | 20.35 | 3.95 | 2.64 | 2.10 | 2.01 | 1.67 | 1.11 | 0.98 |
| Surrogate 95% | 1.72 | 1.57 | 1.48 | 1.42 | 1.37 | 1.33 | 1.29 | 1.26 |
| Supported | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ |

Both methods return **6** supported modes. λ₇ falls inside the null band, so the
spectrum stops there.

### One caution on wording

Five supported *dimensions* is not the same as five or six *blocs*. Five dimensions
can resolve more than six groups. RQ1 fixes the dimensionality; the bloc count is
chosen separately in RQ2 on the silhouette curve.

---

## RQ2 — Do the clusters persist across seasons and intraday, or does the partition reorganise?

### Answer

**The partition persists. It survives every season and every intraday block. It
reorganises only in summer daylight hours — and what actually moves with the clock is
not the membership but the strength of the Europe-wide mode, which falls from 56% at
night to 32% in summer midday.**

### The partition (k = 8, silhouette 0.57)

| Bloc | Zones |
|---|---|
| Balkans + South-East | AL, BG, GR, HR, HU, ME, MK, RO, RS, SI |
| Central-West/East core | AT, CZ, DE_LU, PL, SK |
| Italy + Switzerland | CH, IT_NORTH, IT_CNOR, IT_CSUD, IT_SUD, IT_SICI, IT_SARD |
| Baltics | EE, LV, LT |
| Iberia + France | ES, PT, FR |
| Nordic north | NO_3, NO_4, SE_1, SE_2 |
| North Sea | BE, NL, DK_1, DK_2 |
| Nordic south + Atlantic | FI, IE_SEM, NO_1, NO_2, NO_5, SE_3, SE_4 |

Clustering runs on the **market-mode-removed** correlation matrix — the matrix
rebuilt from modes 2…6. Leaving mode 1 in would make every zone look similar to every
other zone, which is precisely the component RQ1 measures separately.

### Why the comparison needs a null

A season is a quarter of the year, so its correlation matrix is estimated from a
quarter of the data. That alone lowers the Adjusted Rand Index against the full-year
partition, whether or not anything reorganised. **Every stratum is therefore scored
against a permutation null of the same sample size**: for a season, random days; for
an hour block, random hours-of-day; for a season × hour-block cell, both at once. A
stratum counts as reorganised only if its ARI falls below the null's 5th percentile.

| Stratum | Hours | ARI | Null median | Null p05 | Market mode | Verdict |
|---|---|---|---|---|---|---|
| Winter (Dec–Feb) | 2,136 | 0.72 | 0.76 | 0.67 | 51% | persists |
| Spring (Mar–May) | 2,112 | 0.70 | 0.75 | 0.64 | 49% | persists |
| Summer (Jun–Aug) | 2,081 | 0.65 | 0.76 | 0.67 | 51% | **reorganises** |
| Autumn (Sep–Nov) | 2,072 | 0.84 | 0.75 | 0.64 | 43% | persists |
| Night 00–05 UTC | 2,132 | 0.75 | 0.79 | 0.70 | **56%** | persists |
| Morning 06–11 UTC | 2,128 | 0.75 | 0.80 | 0.70 | 49% | persists |
| Midday 12–17 UTC | 1,968 | 0.87 | 0.80 | 0.71 | 43% | persists |
| Evening 18–23 UTC | 2,173 | 0.74 | 0.80 | 0.69 | 48% | persists |

Of the 16 season × hour-block cells, exactly two reorganise:

| Cell | ARI | Null p05 | Market mode |
|---|---|---|---|
| Summer / Morning 06–11 | 0.42 | 0.58 | 36% |
| Summer / Midday 12–17 | 0.44 | 0.58 | **32%** |

**All three reorganising strata are summer, and two of the three are summer daylight
hours.** The hours with the most solar output are the hours when Europe prices least
as one market: the Europe-wide mode weakens and local blocs re-assort.

### Sensitivity to k

The persistence conclusion does not depend on the cluster count.

| k | Silhouette | Mean ARI | Min ARI |
|---|---|---|---|
| 5 | 0.49 | 0.63 | 0.45 |
| 6 | 0.55 | 0.68 | 0.56 |
| 7 | 0.56 | 0.70 | 0.54 |
| **8 (selected)** | **0.57** | **0.75** | **0.65** |
| 9 | 0.58 | 0.75 | 0.66 |
| 10 | 0.57 | 0.78 | 0.70 |

k is the smallest value within 0.01 silhouette of the best, excluding partitions with
a singleton cluster (silhouette rises indefinitely as single zones peel off, so that
guard is necessary) and capped at twice the supported mode count.

### Which zones move

| Most stable | | Least stable | |
|---|---|---|---|
| ES, FR, PT | 0.99 | IE_SEM | 0.21 |
| LT, LV | 0.98 | SK | 0.21 |
| | | DE_LU | 0.33 |
| | | PL | 0.36 |
| | | AT | 0.37 |

Iberia and the Baltics essentially never move. The instability is concentrated on the
**Central-West/East core** (DE_LU, AT, PL, SK, CZ) and on **IE_SEM** — that is, on
the boundary between the Central-European bloc and its neighbours, not inside the
blocs. Germany sits at the seam of the continental system, so its cluster membership
is the one that responds to season and time of day.

---

## RQ3 — Does price co-movement follow the physical interconnection topology, and where does it diverge?

### Answer

**Yes, closely but not exactly — and the exceptions run in both directions. Topology
predicts co-movement at AUC 0.87, but a direct line is neither sufficient (congested
Nordic and HVDC borders) nor necessary (zones two hops apart inside one coupled
bloc).**

### Correlation decays with every hop

| Hops | Pairs | r (levels) | r (shocks) | Hours at an identical price | Mean spread |
|---|---|---|---|---|---|
| 1 | 84 | 0.82 | 0.71 | 15.5% | 17.8 |
| 2 | 151 | 0.70 | 0.58 | 6.3% | 29.1 |
| 3 | 164 | 0.59 | 0.47 | 3.4% | 39.1 |
| 4 | 159 | 0.55 | 0.41 | 2.0% | 43.7 |
| 5 | 121 | 0.50 | 0.36 | 1.0% | 50.5 |
| 6 | 86 | 0.42 | 0.29 | 0.6% | 59.1 |
| 7 | 53 | 0.32 | 0.22 | 0.3% | 70.9 |
| 8 | 28 | 0.21 | 0.15 | 0.1% | 85.7 |
| 9 | 13 | 0.15 | 0.12 | 0.1% | 93.2 |
| 10 | 2 | 0.10 | 0.09 | 0.0% | 102.4 |

Monotone in all four columns. Three statistics say the same thing at the whole-matrix
level:

- **AUC 0.87** (p ≈ 2 × 10⁻²⁹) — the probability that a randomly chosen directly
  connected pair is more correlated than a randomly chosen unconnected pair. High,
  but well short of 1.0.
- **Mantel r = 0.60** (p = 0.0002, 5,000 permutations) between price distance and hop
  distance.
- Mean r: **0.82** on direct borders vs **0.52** without one.

Notably the residual correlations decay in exactly the same shape as the levels, so
this is real propagation of shocks, not the shared calendar.

### Where it diverges — the wire without the price

Directly connected borders with the weakest coupling:

| Border | r (levels) | Hours converged | Mean spread |
|---|---|---|---|
| FI – NO_4 | 0.32 | 1.8% | 33.3 |
| NO_3 – SE_3 | 0.45 | 1.2% | 29.7 |
| NO_1 – NO_3 | 0.49 | 1.2% | 38.0 |
| SE_2 – SE_3 | 0.56 | 3.3% | 30.5 |
| EE – FI | 0.58 | 26.4% | 42.1 |
| FI – SE_1 | 0.58 | 11.6% | 24.1 |
| LT – PL | 0.62 | 16.5% | 39.8 |

These are almost all **internal Nordic borders**, plus the Baltic interconnectors.
Hydro reservoir management in the north and persistent congestion mean the price
almost never converges even though the line exists. NO_1–NO_3 converges in 1.2% of
hours: the constraint binds essentially all the time.

The same pattern shows on the continental side. Ranked by mean spread among borders
that converge in under 5% of hours: FR–IT_NORTH (54.5 EUR/MWh), PL–SE_4 (47.0),
CH–FR (42.1, converging in 0.04% of hours), DK_1–SE_3 (38.3), DE_LU–SE_4 (34.0),
DE_LU–FR (32.8). A high-capacity border between two large systems can still price
apart nearly every hour.

### Where it diverges — the price without the wire

Non-adjacent pairs with the tightest coupling:

| Pair | Hops | r (levels) | Hours converged |
|---|---|---|---|
| HR – RO | 2 | 0.96 | 9.2% |
| IT_CSUD – IT_NORTH | 2 | 0.96 | 86.1% |
| BG – HU | 2 | 0.96 | 11.6% |
| DK_1 – DK_2 | 2 | 0.95 | 32.0% |
| IT_SARD – IT_SUD | 2 | 0.95 | 86.5% |
| BG – HR | 2 | 0.95 | 8.7% |
| HR – SK | 2 | 0.93 | 8.9% |

Two mechanisms, cleanly separated by the convergence column:

- **Italian internal zones** converge in ~86% of hours. They are one market clearing
  together; the intermediate zone is a formality.
- **Balkan / CEE pairs** correlate at 0.96 but converge in under 12% of hours. They
  move together because they share the same drivers and the same coupled region,
  while still pricing apart — correlation without convergence.

`DK_1 – DK_2` is a **topology-data gap, not a market finding**: the Great Belt HVDC
link physically connects them, but neither `config/zones.yaml` nor the ENTSO-E flow
and NTC data reports that border, so it is scored as two hops. Worth fixing before
this table is published anywhere.

### Does capacity explain it?

Partly. Over the 30 adjacent borders with a genuine per-border NTC value, log
capacity correlates **r = 0.39** with price coupling. Bigger borders do couple more,
but capacity is clearly not the whole story — what separates a coupled border from a
congested one is how often the capacity binds and which market-coupling region the
zones belong to.

### Data caveat on flows and NTC

This needs stating plainly, because it constrains what RQ3 can claim.

**ENTSO-E republishes each zone's aggregate export against every one of its borders.**
The project's `flow_validation` already found this for physical flows; the same
defect is present in the A61 net transfer capacities. France reports 2,801 MW
identically on BE, DE_LU and IT_NORTH; Germany reports 1,185 MW on 8 of its 11
borders; Austria reports 711 MW on 6 of 7.

Those are zone aggregates, not border capacities, and using them would manufacture a
result. They are excluded:

| Source | Available | Usable per-border |
|---|---|---|
| Net transfer capacity (A61) | 108 borders | **37** |
| Directed physical flows (A11) | 177 pairs | **2** |

Every correlation, convergence and spread figure in this section comes from the
**price panel**, which has no such defect and is unaffected. The flow and NTC columns
are shown only where a genuine per-border value exists, and are blank otherwise.

---

## What the three answers say together

1. Europe is **one market plus five cluster dimensions** — the common mode is large
   (47%) but nowhere near total, and a quarter of the variance is idiosyncratic.
2. Those clusters are **structural, not seasonal**. They hold through winter and
   summer, night and evening. The only genuine reorganisation is summer daylight,
   when solar weakens the common mode to 32%.
3. The clusters **follow the grid, with two systematic exceptions**: congested
   borders where the wire cannot enforce one price, and coupled blocs where the
   market clears zones together regardless of direct connection.

The recurring theme is that **market-coupling membership, not copper, sets the
partition**. That is what makes the Nordic internal borders and the Balkan
non-borders the two most informative parts of the analysis.

## Open items

- `DK_1 – DK_2` (Great Belt) missing from the topology config and from ENTSO-E
  flow/NTC data — fix before publishing the RQ3 divergence tables.
- GB has no 2025 ENTSO-E data, so the whole GB–continent interface is invisible to
  all three RQs.
- Per-border NTC is available for 37 of 108 borders. An alternative capacity source
  (PyPSA-Eur line ratings) would let RQ3 test the capacity hypothesis properly.
- Extending the panel to a second year would show whether the 2025 partition is
  itself stable year to year — RQ2 currently answers persistence *within* one year.
