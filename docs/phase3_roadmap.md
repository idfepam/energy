# Phase 3 roadmap (Stefan feedback, Sep 2026)

## 1. Zone gap fixes (short term)
- [ ] Retry **GB** with `UK` / alternative EIC in ENTSO-E collector
- [ ] Investigate **AL** generation (A75) — prices OK, PSR series empty
- [ ] Document **BA** — load+gen OK, DA prices absent (market structure)
- [ ] Consolidate **imbalance** into processed parquet (40 zones)

## 2. Seasonality decomposition
- [ ] STL / seasonal_decompose on `prices_2025` and `load_2025` per zone
- [ ] Export trend / seasonal / residual parquets
- [ ] Report: intraday (24h) and quarterly patterns (Stefan’s hint)
- [ ] Use **residuals** (or deseasonalised series) as input to TE

## 3. Transfer Entropy dependency layer
- [ ] Reference: [Tabachová et al. 2026 — Rényi TE](https://arxiv.org/pdf/2601.01497)
- [ ] Implement classical TE (α=1) first: `pyinform` or custom k-NN estimator
- [ ] Pairwise zone TE on deseasonalised day-ahead prices (directed edges)
- [ ] Optional: RTE with α sweep for price spikes
- [ ] New graph manifest: `dependency_graph_2025_te.json`
- [ ] Compare TE vs Pearson vs physical flows in validation doc

## 4. Frontend dashboard
- [ ] Stack: static site or Vite + React; serve from `docs/dashboard/`
- [ ] Views: map, zone detail, TE matrix heatmap, seasonality charts, coverage table
- [ ] Data: read from `data/manifests/*.json` + processed parquets (or precomputed JSON for browser)
- [ ] Reuse `map_leaflet.json` and graph manifests

## 5. Meeting agenda (Mon / Thu)
- Confirm TE as primary dynamic edge definition
- Scheduled exchanges vs physical flows
- Frontend scope for Stefan review
- Interdisciplinary lecture / course logistics (separate from data work)
