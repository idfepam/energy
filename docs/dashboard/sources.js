/** Data source and methodology blocks per dashboard panel. */
(function (global) {
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  function row(label, value) {
    return (
      '<tr><th scope="row">' + esc(label) + '</th><td>' + value + '</td></tr>'
    );
  }

  function fileLink(path) {
    return '<code>' + esc(path) + '</code>';
  }

  const STATIC_SOURCES_EXPLAIN =
    '<details class="te-params static-sources">' +
    '<summary>Non-ENTSO-E reference layers (geography &amp; context)</summary>' +
    '<div class="te-params-body">' +
    '<ul class="te-params-list">' +
    '<li><strong>PyPSA-Eur / OpenStreetMap</strong> — European transmission grid from Zenodo (ODbL). ' +
    'Substation coordinates → zone/country centroids on the map; ~9k line geometries in the static merge. ' +
    '<code>static-osm</code> → <code>data/raw/static/osm_grid/</code>.</li>' +
    '<li><strong>GEM (Global Energy Monitor)</strong> — Global Integrated Power Tracker (GIPT): plant capacity by country, ' +
    'attached to graph nodes after <code>merge-static</code> (reference only — not used in edge weights). ' +
    '<code>data/raw/static/gem/</code>.</li>' +
    '<li><strong>config/zones.yaml</strong> — Project zone list (45 bidding zones), EIC codes, and border neighbours. ' +
    'Defines TE border pairs and structural edges; not from an API.</li>' +
    '<li><strong>Map basemap</strong> — CARTO Positron tiles (OpenStreetMap-derived background).</li>' +
    '</ul>' +
    '<p class="te-params-note"><em>Dynamic</em> edges (flow, price r, TE) come from ENTSO-E time series. ' +
    'Static layers provide coordinates and geographic context only.</p>' +
    '</div></details>';

  const MAP_LAYER_SOURCES = {
    flow: {
      title: 'Physical flow layer',
      source:
        '<strong>ENTSO-E Transparency Platform</strong>, document <strong>A11</strong> (12.1.G) — ' +
        'physical cross-border power flow, MW, hourly.',
      how:
        'Collected per zone × month via API (<code>collect --year</code>). Validated in ' +
        '<code>validate-flows</code>: duplicate-export detection, coverage checks. ' +
        'One canonical directed edge per undirected border; map strength = mean <em>absolute</em> hourly MW (2025).',
      files: [
        'data/processed/entsoe/flows_{year}.parquet',
        'data/manifests/flow_validation_{year}.json',
        'data/manifests/dependency_graph_{year}.json',
      ],
      cli: 'validate-flows --year {year}  →  build-graph --year {year}',
    },
    price: {
      title: 'Price coupling layer',
      source:
        '<strong>ENTSO-E A44</strong> (12.1.D) — day-ahead market clearing price, EUR/MWh, hourly.',
      how:
        'Hourly prices pivoted by zone; <strong>Pearson r</strong> computed on all pairs with ≥30 days overlap. ' +
        'Graph threshold |r| ≥ 0.85; map “Strongest” uses |r| ≥ 0.80. Undirected edges (↔). ' +
        '{zones_with_prices} of {target_zones} target zones have full-year prices.',
      files: [
        'data/processed/entsoe/prices_{year}.parquet',
        'data/manifests/dependency_graph_{year}.json',
      ],
      cli: 'build-graph --year {year}  →  build-dashboard --year {year}',
    },
    te: {
      title: 'Transfer entropy layer',
      source:
        '<strong>ENTSO-E A44</strong> day-ahead prices → seasonally decomposed → ' +
        '<code>prices_deseasonalised_{year}.parquet</code>.',
      how:
        'Estimator: k-NN Rényi transfer entropy (Leonenko; Tabachová et al. 2026), reported as effective RTE in bits. ' +
        'Map uses <strong>177 config border directions</strong> from <code>config/zones.yaml</code>. ' +
        '“Strongest” = TE ≥ {te_min} bits; “All” includes borders with TE = 0 (no estimate). ' +
        '{te_params}',
      files: [
        'data/processed/entsoe/prices_deseasonalised_{year}.parquet',
        'data/manifests/dashboard/transfer_entropy_{year}.json',
        'data/manifests/dependency_graph_{year}_te.json',
      ],
      cli: 'decompose-seasonality --year {year}  →  compute-te --year {year}  →  build-dashboard --year {year}',
      reference: '{te_reference}',
    },
  };

  const PANEL_SOURCES = {
    prices: {
      title: 'Day-ahead prices',
      source:
        '<strong>ENTSO-E Transparency Platform</strong> — document <strong>A44</strong> (12.1.D), ' +
        'day-ahead price in <strong>EUR/MWh</strong>, hourly UTC timestamps.',
      how:
        'API collection (<code>collect --year {year}</code>) stores rows in SQLite manifest then ' +
        '<code>prices_{year}.parquet</code>. Chart = monthly mean per zone ({chart_zones} zones shown). ' +
        'Table = annual mean, min/max hourly, hour count for {year}. ' +
        '{zones_with_prices}/{target_zones} zones have full-year data.',
      files: [
        'data/processed/entsoe/prices_{year}.parquet',
        'data/manifests/collection.db',
      ],
      cli: 'collect --year {year}',
    },
    seasonality: {
      title: 'Seasonality decomposition',
      source:
        '<strong>Prices:</strong> ENTSO-E A44 → <code>prices_{year}.parquet</code>.<br>' +
        '<strong>Load:</strong> ENTSO-E A65 (6.1.A) actual consumption, MW → <code>load_{year}.parquet</code>.',
      how:
        '{seasonality_method}. Removed in order: hour-of-day → day-of-week → month-of-year → 7-day trend. ' +
        'Charts show mean profiles; tables report variance explained (HOD/DOW/MOY) and residual σ. ' +
        'Residual price series feeds transfer entropy.',
      files: [
        'data/processed/entsoe/prices_deseasonalised_{year}.parquet',
        'data/processed/entsoe/load_deseasonalised_{year}.parquet',
        'data/manifests/dashboard/seasonality_prices_{year}.json',
        'data/manifests/dashboard/seasonality_load_{year}.json',
      ],
      cli: 'decompose-seasonality --year {year} --all',
    },
    te: {
      title: 'Transfer entropy',
      source:
        'Deseasonalised day-ahead prices (<code>prices_deseasonalised_{year}.parquet</code>), ' +
        'originally from ENTSO-E A44.',
      how:
        'Directed information flow in <strong>bits</strong> from deseasonalised ENTSO-E A44 prices. ' +
        'Minimum TE for listed graph edges: <strong>{te_min}</strong> bits. ' +
        'Full run: {te_edge_count} directed pairs. {te_params}',
      files: [
        'data/manifests/dashboard/transfer_entropy_{year}.json',
        'data/manifests/dependency_graph_{year}_te.json',
      ],
      cli: 'compute-te --year {year} --min-te {te_min}',
      reference: '{te_reference}',
    },
    mismatch: {
      title: 'Price vs physical flow',
      source:
        '<strong>ENTSO-E A11</strong> physical flows and <strong>A44</strong> day-ahead prices. TE from the k-NN graph when present.',
      how:
        'Each neighbouring border: mean |MW|, Pearson r, max directed TE. Classes use median flow as the high-flow cut, |r| ≥ 0.85 (same as the price graph), TE ≥ 0.02. Duplicate-export A11 rows are still aggregated as mean |MW| — interpret directions with flow validation in mind.',
      files: [
        'data/processed/entsoe/flows_{year}.parquet',
        'data/processed/entsoe/prices_{year}.parquet',
        'data/manifests/meeting_analyses_{year}.json',
      ],
      cli: 'analyze-meeting --year {year}',
    },
    regimes: {
      title: 'TE regimes and nested scales',
      source: 'Deseasonalised A44 prices. Discrete Schreiber TE (quantile bins) on subsampled hours.',
      how:
        'Border pairs: TE in both directions per HOD / DOW / season / month. Nested corridor set: year TE vs averages of monthly, weekly, and hour-of-day TE. Reversal = leader sign(net TE) flips across bins with |net| ≥ 0.01 bits.',
      files: [
        'data/processed/entsoe/prices_deseasonalised_{year}.parquet',
        'data/manifests/dashboard/meeting_analyses_{year}.json',
      ],
      cli: 'analyze-meeting --year {year}',
    },
    network: {
      title: 'Network and grid',
      source:
        'Price/flow/TE graphs plus <strong>PyPSA-Eur OSM</strong> buses/lines and <strong>GEM GIPT</strong> operating plants.',
      how:
        'Hub strength = sum of |edge weights|. Price communities = connected components of |r| ≥ 0.85. Grid tables count substations, voltages, HVDC links, and GEM MW by country/type.',
      files: [
        'data/manifests/dependency_graph_{year}.json',
        'data/raw/static/osm_grid/',
        'data/raw/static/gem/plants_eu_20260822.parquet',
      ],
      cli: 'analyze-meeting --year {year}',
    },
    coverage: {
      title: 'Data coverage audit',
      source:
        '<strong>ENTSO-E Transparency Platform API</strong> — dynamic time series in the gap table ' +
        '(A44 prices, A65 load, A75 generation, A85 imbalance, A11 flows).',
      how:
        'After collection, zones missing any month in {year} are flagged in ' +
        '<code>data/manifests/gaps_report.json</code>. Target list = {target_zones} zones in ' +
        '<code>config/zones.yaml</code>. Counts show zones with a complete calendar year per ENTSO-E dataset.',
      static: STATIC_SOURCES_EXPLAIN,
      files: [
        'data/manifests/gaps_report.json',
        'data/manifests/collection.db',
        'data/processed/static/zone_geo.parquet',
        'data/raw/static/osm_grid/',
        'data/raw/static/gem/',
      ],
      cli: 'collect --year {year}  ·  static-osm  ·  static-gem  ·  merge-static --year {year}',
    },
  };

  function fillTemplate(text, meta) {
    if (!text) return '';
    return text.replace(/\{(\w+)\}/g, function (_, key) {
      const v = meta[key];
      return v == null ? '—' : String(v);
    });
  }

  function renderSourceBlock(spec, meta, opts) {
    opts = opts || {};
    const title = opts.title || spec.title;
    let html =
      '<details class="data-sources"' + (opts.open === false ? '' : ' open') + '>' +
      '<summary>Data source &amp; method</summary>' +
      '<div class="data-sources-body">';

    if (spec.intro) {
      html += '<p class="data-sources-intro">' + fillTemplate(spec.intro, meta) + '</p>';
    }

    html += '<table class="data-sources-table"><tbody>';
    html += row('Source', fillTemplate(spec.source, meta));
    html += row('How used', fillTemplate(spec.how, meta));
    if (spec.static) {
      html += row('Also used', fillTemplate(spec.static, meta));
    }
    if (spec.files && spec.files.length) {
      html +=
        row(
          'Files',
          '<ul class="data-sources-files">' +
            spec.files
              .map(function (f) {
                return '<li>' + fileLink(fillTemplate(f, meta)) + '</li>';
              })
              .join('') +
            '</ul>'
        );
    }
    if (spec.cli) {
      html += row('Pipeline', '<code>' + esc(fillTemplate(spec.cli, meta)) + '</code>');
    }
    if (spec.reference) {
      html += row('Reference', esc(fillTemplate(spec.reference, meta)));
    }
    html += row('Dashboard built', esc(meta.generated_at || '—'));
    html += '</tbody></table></div></details>';
    return html;
  }

  function buildMeta(data) {
    const D = data || {};
    const th = D.map_layers?.thresholds || {};
    const teParams =
      (global.DASHBOARD_GLOSSARY && global.DASHBOARD_GLOSSARY.TE_PARAMS_EXPLAIN) || '';
    return {
      year: D.year || 2025,
      generated_at: D.generated_at || '',
      target_zones: D.target_zones || 45,
      zones_with_prices: D.zones_with_prices || '—',
      chart_zones: Object.keys(D.monthly_prices || {}).length || '—',
      te_method: D.sources_meta?.te_method || D.te_method || 'k-NN Rényi TE (Leonenko), effective RTE',
      te_min: th.te_min != null ? th.te_min : D.sources_meta?.te_min || 0.003,
      te_reference:
        D.sources_meta?.te_reference ||
        'Tabachová et al. (2026) arXiv:2601.01497',
      te_edge_count: D.te_edge_count || '—',
      seasonality_method:
        D.seasonality?.method ||
        D.sources_meta?.seasonality_method ||
        'Sequential HOD → DOW → MOY removal + 7-day trend',
      price_min_r: th.price_min_r != null ? th.price_min_r : 0.85,
      price_strongest_floor: th.price_strongest_floor != null ? th.price_strongest_floor : 0.8,
      flow_edges: D.flow_edges_count || D.graph_stats?.flow_edges_validated || '—',
      price_edges: D.price_edges_count || D.graph_stats?.price_edges || '—',
      te_params: teParams,
    };
  }

  function renderSourcesPanel(containerId, panelKey, data) {
    const el = document.getElementById(containerId);
    if (!el) return;
    const meta = buildMeta(data);
    const spec = PANEL_SOURCES[panelKey];
    if (!spec) return;
    el.innerHTML = renderSourceBlock(spec, meta);
  }

  function renderMapLayerSource(containerId, layerKey, data) {
    const el = document.getElementById(containerId);
    if (!el) return;
    const meta = buildMeta(data);
    const layerSpec = MAP_LAYER_SOURCES[layerKey] || MAP_LAYER_SOURCES.flow;
    const layerLabel =
      layerKey === 'flow'
        ? 'Physical flow'
        : layerKey === 'price'
          ? 'Price coupling (Pearson r)'
          : 'Transfer entropy';

    const fileSet = {};
    [
      'data/manifests/dependency_graph_{year}.json',
      'data/processed/static/zone_geo.parquet',
      'docs/dashboard/data.js',
    ]
      .concat(layerSpec.files || [])
      .forEach(function (f) {
        fileSet[fillTemplate(f, meta)] = true;
      });

    const combined = {
      title: 'Map — ' + layerLabel,
      intro:
        'Edge lines = ENTSO-E-derived metrics below. Zone dot positions from <strong>PyPSA-Eur OSM</strong> substation centroids ' +
        '(<code>zone_geo.parquet</code>). Basemap: CARTO / OpenStreetMap.',
      source: layerSpec.source,
      how: layerSpec.how,
      static: STATIC_SOURCES_EXPLAIN,
      files: Object.keys(fileSet),
      cli: layerSpec.cli,
      reference: layerSpec.reference,
    };

    el.innerHTML = renderSourceBlock(combined, meta);
  }

  global.DASHBOARD_SOURCES = {
    STATIC_SOURCES_EXPLAIN,
    PANEL_SOURCES,
    MAP_LAYER_SOURCES,
    buildMeta,
    renderSourcesPanel,
    renderMapLayerSource,
  };
})(window);
