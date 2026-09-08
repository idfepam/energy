# Data Dictionary — ENTSO-E Collection (2025)

**Project:** Data-Driven Dependency Mapping of European Energy Infrastructure  
**Source:** [ENTSO-E Transparency Platform](https://transparency.entsoe.eu/)

This document explains every naming convention, field, and code used in the collected data.

---

## 1. Geographic hierarchy

European electricity data uses **bidding zones**, not always countries:

```
Country (ISO2)          e.g. DE, FR, IT
    └── Bidding zone      e.g. DE_LU, IT_NORTH, SE_3
            └── Time series (prices, load, generation…)
```

A **bidding zone** is the smallest market unit for day-ahead pricing. Some countries have one zone (France = `FR`), others are split (Italy has 6 zones, Sweden has 4, Norway has 5).

Reference files:
- `config/zones.yaml` — zone list + neighbor borders
- `data/processed/static/zone_reference.parquet` — zone → country mapping + EIC codes
- `data/processed/static/zone_geo.parquet` — zone + approximate lat/lon (from OSM substations)
- `data/processed/static/country_centroids.parquet` — country-level coordinates

---

## 2. Bidding zone codes (all 43 collected)

| Code | Full name | Country (ISO2) | Notes |
|------|-----------|----------------|-------|
| `AL` | Albania | AL | |
| `AT` | Austria | AT | |
| `BA` | Bosnia and Herzegovina | BA | Load only; no prices in 2025 |
| `BE` | Belgium | BE | |
| `BG` | Bulgaria | BG | |
| `CH` | Switzerland | CH | Not EU, coupled market |
| `CZ` | Czech Republic | CZ | |
| `DE_LU` | Germany/Luxembourg | DE | **Use this, not `DE`** for prices |
| `DK_1` | Denmark West (DK1) | DK | Jutland / western Denmark |
| `DK_2` | Denmark East (DK2) | DK | Zealand / eastern Denmark |
| `EE` | Estonia | EE | |
| `ES` | Spain | ES | Iberian market |
| `FI` | Finland | FI | |
| `FR` | France | FR | |
| `GR` | Greece | GR | |
| `HR` | Croatia | HR | |
| `HU` | Hungary | HU | |
| `IE_SEM` | Ireland (Single Electricity Market) | IE | SEM = all-island market |
| `IT_NORTH` | Italy North | IT | TSO zone: North |
| `IT_CNOR` | Italy Centre-North | IT | |
| `IT_CSUD` | Italy Centre-South | IT | |
| `IT_SUD` | Italy South | IT | |
| `IT_SICI` | Italy Sicily | IT | Island — limited cross-border |
| `IT_SARD` | Italy Sardinia | IT | Island |
| `LT` | Lithuania | LT | |
| `LV` | Latvia | LV | |
| `ME` | Montenegro | ME | |
| `MK` | North Macedonia | MK | |
| `NL` | Netherlands | NL | |
| `NO_1` | Norway SE (Oslo area) | NO | Norwegian price zones 1–5 |
| `NO_2` | Norway SW | NO | |
| `NO_3` | Norway Central | NO | |
| `NO_4` | Norway North | NO | |
| `NO_5` | Norway West | NO | |
| `PL` | Poland | PL | |
| `PT` | Portugal | PT | Iberian market with ES |
| `RO` | Romania | RO | |
| `RS` | Serbia | RS | |
| `SE_1` | Sweden Luleå (north) | SE | Swedish bidding zones 1–4 |
| `SE_2` | Sweden Sundsvall | SE | |
| `SE_3` | Sweden Stockholm | SE | |
| `SE_4` | Sweden Malmö (south) | SE | |
| `SI` | Slovenia | SI | |
| `SK` | Slovakia | SK | |

**Not collected:** `CY` (Cyprus — API unsupported), `GB`/`UK` (no 2025 data returned)

**EIC codes:** Each zone has an ENTSO-E Energy Identification Code (e.g. `DE_LU` → `10Y1001A1001A83F`). See `zone_reference.parquet` column `eic_code`.

---

## 3. Datasets and ENTSO-E document types

| Our name | ENTSO-E article | Doc type | What it measures |
|----------|-----------------|----------|------------------|
| `day_ahead_prices` | 12.1.D | A44 | Market clearing price for next-day delivery |
| `actual_load` | 6.1.A | A65 | Total electricity consumed in the zone |
| `generation_actual` | 16.1.B&C | A75 | Electricity produced, split by fuel type |
| `imbalance_prices` | 17.1.G | A85 | Price for balancing energy (up/down) |
| `crossborder_flows` | 12.1.G | A11 | Physical MW flowing between two zones |
| `scheduled_exchanges` | 12.1.E | A09 | Commercially scheduled MW between zones |
| `net_transfer_capacity` | 11.1 | A61 | Maximum transferable MW (day-ahead NTC) |

---

## 4. Parquet column reference

### Zone-level files (`prices`, `load`, `generation`, `imbalance`)

| Column | Type | Description |
|--------|------|-------------|
| `timestamp` | datetime (UTC) | Start of the measurement interval |
| `value` | float | Main numeric value (see unit below) |
| `zone` | string | Bidding zone code (see table above) |
| `currency` | string | `EUR` (prices only) |
| `price_unit` | string | `MWH` = EUR/MWh (prices only) |
| `quantity_unit` | string | `MW` for load/generation/flows |
| `psr_type` | string | Fuel type name or code (generation only) |
| `dataset` | string | Internal dataset name |
| `period_start` | string | Query start date |
| `period_end` | string | Query end date |

### Border-pair files (`flows`, `scheduled_exchanges`, `net_transfer_capacity`)

| Column | Type | Description |
|--------|------|-------------|
| `timestamp` | datetime (UTC) | Interval start |
| `value` | float | MW (positive = flow direction from → to) |
| `from_zone` | string | Exporting bidding zone |
| `to_zone` | string | Importing bidding zone |
| `in_domain` | string | ENTSO-E EIC code of receiving domain |
| `quantity_unit` | string | Always `MW` |

**Border pair notation:** `DE_LU>NL` means power flowing from Germany/Luxembourg into Netherlands.

---

## 5. PSR types (generation fuel codes)

PSR = Power System Resource. Generation data includes a `psr_type` column:

| Code | Name | Category |
|------|------|----------|
| B01 | Biomass | Renewable |
| B02 | Fossil Brown coal/Lignite | Fossil |
| B03 | Fossil Coal-derived gas | Fossil |
| B04 | Fossil Gas | Fossil |
| B05 | Fossil Hard coal | Fossil |
| B06 | Fossil Oil | Fossil |
| B07 | Fossil Oil shale | Fossil |
| B08 | Fossil Peat | Fossil |
| B09 | Geothermal | Renewable |
| B10 | Hydro Pumped Storage | Storage |
| B11 | Hydro Run-of-river | Renewable |
| B12 | Hydro Water Reservoir | Renewable |
| B13 | Marine | Renewable |
| B14 | Nuclear | Low-carbon |
| B15 | Other renewable | Renewable |
| B16 | Solar | Renewable |
| B17 | Waste | Other |
| B18 | Wind Offshore | Renewable |
| B19 | Wind Onshore | Renewable |
| B20 | Other | Other |

Our processed data stores the **human-readable name** (e.g. `Solar`, `Nuclear`), not always the B-code.

---

## 6. Units summary

| Dataset | Unit | Sign convention |
|---------|------|-----------------|
| Day-ahead prices | EUR/MWh | Always positive (can go negative in crisis) |
| Imbalance prices | EUR/MWh | Can be negative |
| Load | MW | Always positive |
| Generation | MW | Always positive |
| Cross-border flows | MW | Positive = from `from_zone` to `to_zone` |
| NTC | MW | Maximum transferable capacity |

---

## 7. Geographic / static data available

### Already downloaded

| Source | File | Geo content |
|--------|------|-------------|
| **PyPSA-Eur OSM grid** | `data/raw/static/osm_grid/buses_*.csv` | Substation lat/lon (`x`, `y`), `country` ISO2, `geometry` WKT |
| **PyPSA-Eur OSM grid** | `data/raw/static/osm_grid/lines_*.csv` | Transmission line geometry, voltage (kV), length (km) |
| **PyPSA-Eur OSM grid** | `data/raw/static/osm_grid/links_*.csv` | HVDC links between zones |
| **Zone reference** | `data/processed/static/zone_geo.parquet` | Zone → country → centroid lat/lon |
| **Country centroids** | `data/processed/static/country_centroids.parquet` | Mean substation position per country |

OSM grid covers **36 countries** (AL, AT, BA, BE, BG, CH, CZ, DE, DK, EE, ES, FI, FR, GB, GR, HR, HU, IE, IT, LT, LU, LV, MD, ME, MK, NL, NO, PL, PT, RO, RS, SE, SI, SK, UA, XK).

### Available but not yet collected

| Source | Geo content | How to get |
|--------|-------------|------------|
| **Global Energy Monitor** | Power plant lat/lon, capacity, fuel, country | `energy-collect static-gem --url <XLSX>` |
| **ENTSO-E web UI** | Official zone maps | transparency.entsoe.eu (manual) |
| **Eurostat** | Country energy statistics | ec.europa.eu/eurostat |
| **JRC Open Power System Data** | Zone/country mappings | research.jrc.ec.europa.eu |

### Linking time-series to geography

```python
import pandas as pd

zones = pd.read_parquet("data/processed/static/zone_geo.parquet")
prices = pd.read_parquet("data/processed/entsoe/prices_2025.parquet")

# Join country + coordinates to prices
df = prices.merge(zones[["zone_code", "country_iso2", "country_name", "centroid_lat", "centroid_lon"]],
                  left_on="zone", right_on="zone_code")
```

Build/update geo tables:
```bash
python3 scripts/build_geo_reference.py
```

---

## 8. Processed files (ready for analysis)

| File | Rows | Description |
|------|------|-------------|
| `prices_2025.parquet` | 641k | All zones, hourly, 2025 |
| `load_2025.parquet` | 1.0M | All zones, hourly |
| `generation_2025.parquet` | 7.1M | All zones × fuel types |
| `flows_2025.parquet` | 2.5M | All border pairs, hourly |
| `zone_geo.parquet` | 45 | Zone metadata + coordinates |
| `country_centroids.parquet` | 36 | Country centroids from OSM |

---

## 9. Known data quirks

1. **`DE` vs `DE_LU`:** Always use `DE_LU` for German prices/load. `DE` alone is not a valid bidding zone in ENTSO-E.
2. **Italian zones:** Six internal zones reflect TSO dispatch areas, not political regions.
3. **Flow duplicates:** Some exporters (e.g. FR) return identical values for all outgoing borders — likely aggregate export, not per-border metering. Validate before using as graph edges.
4. **Timestamps:** All UTC. CET/CEST is UTC+1/+2 — German hour 12:00 = 11:00 UTC in winter.
5. **GB missing:** Great Britain data not returned for 2025 via current zone code; try `UK` or post-Brexit EIC separately.

---

## 10. File structure

```
data/
├── raw/entsoe/{dataset}/{zone_or_pair}/{period}.parquet   # Raw API pulls
├── processed/entsoe/{prices,load,generation,flows}_2025.parquet
├── processed/static/
│   ├── zone_reference.parquet      # Zone names, countries, EIC codes
│   ├── zone_geo.parquet            # Zones + lat/lon centroids
│   └── country_centroids.parquet   # Country-level coordinates
└── raw/static/osm_grid/            # Transmission grid geometry
```

---

*Generated for project with supervisor Stefan. Update after adding GEM plant data or GB zone fix.*
