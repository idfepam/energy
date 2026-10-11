(function () {
  const D = window.DASHBOARD_DATA;
  if (!D) {
    document.body.innerHTML =
      '<p style="padding:2rem;font-family:system-ui">Run: <code>PYTHONPATH=src python3 -m energy_collect.cli build-dashboard --year 2025</code></p>';
    return;
  }

  const charts = { price: null, hod: null, quarter: null, monthSeason: null, nestedTe: null, nestedHod: null, substations: null, gemType: null, mismatchScatter: null, tePair: null, teNet: null, rq1Spectrum: null, rq1Variance: null, rq2Ari: null, rq2Market: null, rq3Hops: null, shapeProfile: null, shapeNeg: null, shapeDuration: null, shapeAlign: null };
  const G = window.DASHBOARD_GLOSSARY || {};
  const S = window.DASHBOARD_SOURCES || {};
  const Z = D.zone_names || {};
  const zLabel = (code) => (G.zoneLabel ? G.zoneLabel(code, Z) : code);
  const zCell = (code) =>
    '<div class="zone-cell">' + (G.formatZoneCell ? G.formatZoneCell(code, Z) : '<span class="zone-code">' + code + '</span>') + '</div>';
  const zChartLabel = (code) => code + ' — ' + zLabel(code);

  // --- Theme: colours come from CSS custom properties so light/dark stay in sync ---
  const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const isDark = () => document.documentElement.dataset.theme !== 'light';
  const PAL = {
    blue: '#3b82f6', cyan: '#22d3ee', teal: '#14b8a6', green: '#10b981', violet: '#8b5cf6',
    rose: '#f43f5e', amber: '#f59e0b', orange: '#fb923c', slate: '#94a3b8',
  };
  const GRID = () => cssVar('--chart-grid');
  const MUTED = () => cssVar('--chart-muted');
  const MUTED_SOFT = () => cssVar('--chart-muted-soft');
  const alpha = (hex, a) => hex + Math.round(a * 255).toString(16).padStart(2, '0');

  function applyChartTheme() {
    if (!window.Chart) return;
    const d = Chart.defaults;
    d.font.family = "'Inter', system-ui, sans-serif";
    d.color = cssVar('--chart-text');
    d.borderColor = GRID();
    d.plugins.title.color = cssVar('--text');
    Object.assign(d.plugins.tooltip, {
      backgroundColor: cssVar('--tooltip-bg'),
      titleColor: cssVar('--text'),
      bodyColor: cssVar('--text-2'),
      borderColor: cssVar('--border-strong'),
      borderWidth: 1,
      padding: 10,
      cornerRadius: 10,
      boxPadding: 4,
    });
    d.elements.line.borderWidth = 2.25;
    d.elements.point.hoverRadius = 5;
    d.elements.bar.borderRadius = 3;
    d.animation.duration = 650;
  }
  applyChartTheme();

  function uniqueCodes(codes) {
    return [...new Set(codes.filter(Boolean))];
  }

  function formatMissingZones(missingStr) {
    if (!missingStr || missingStr === '—') return '—';
    return missingStr.split(',').map(function (part) {
      const code = part.trim();
      return '<span class="zone-chip"><strong>' + code + '</strong><small>' + zLabel(code) + '</small></span>';
    }).join(' ');
  }
  const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  function formatMonth(ym) {
    const [y, m] = ym.split('-').map(Number);
    return `${MONTH_NAMES[m - 1]} ${y}`;
  }

  function teInterpretation(bits) {
    if (bits >= 0.08) return 'Strong directed coupling';
    if (bits >= 0.04) return 'Moderate information flow';
    if (bits >= 0.02) return 'Weak but detectable';
    return 'Minimal';
  }

  let chartDefaults;
  const buildChartDefaults = () => ({
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { position: 'bottom', labels: { boxWidth: 12, padding: 14, font: { size: 11 } } },
      tooltip: { mode: 'index', intersect: false },
    },
    scales: {
      x: { grid: { display: false }, ticks: { maxRotation: 45, minRotation: 0, font: { size: 11 } } },
      y: {
        title: { display: true, text: 'EUR/MWh', font: { size: 11 } },
        grid: { color: GRID() },
        ticks: { font: { size: 11 } },
      },
    },
  });
  chartDefaults = buildChartDefaults();

  document.getElementById('subtitle').textContent =
    `ENTSO-E ${D.year} · ${D.zones_with_prices || '—'} zones with prices · updated ${new Date(D.generated_at).toLocaleDateString()}`;

  // --- Tabs (lazy chart render) ---
  document.querySelectorAll('.tab').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach((b) => b.classList.remove('active'));
      document.querySelectorAll('.panel').forEach((p) => p.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById('panel-' + btn.dataset.tab).classList.add('active');
      renderTab(btn.dataset.tab);
    });
  });

  function renderTab(tab) {
    if (tab === 'map') {
      map.invalidateSize();
      renderMapEdges();
    }
    if (tab === 'prices') renderPriceChart();
    if (tab === 'seasonality') renderSeasonalityCharts();
    if (tab === 'regimes') {
      renderNestedTeChart();
      renderNestedHodChart();
      renderRegimeLineCharts();
    }
    if (tab === 'mismatch') renderMismatchScatter();
    if (tab === 'network') renderNetworkCharts();
    if (tab === 'shape') renderShapeCharts();
  }

  // --- Map ---
  const MAP_PALETTES = {
    light: {
      flow: { weak: [191, 219, 254], strong: [29, 78, 216] },
      price: { weak: [254, 215, 170], strong: [194, 65, 12] },
      te: { weak: [221, 214, 254], strong: [109, 40, 217] },
    },
    dark: {
      flow: { weak: [30, 64, 110], strong: [103, 232, 249] },
      price: { weak: [96, 56, 20], strong: [252, 211, 77] },
      te: { weak: [62, 40, 110], strong: [216, 180, 254] },
    },
  };
  const MAP_LABELS = {
    flow: { label: 'Mean flow (MW)', unit: 'MW' },
    price: { label: 'Price correlation (r)', unit: 'r' },
    te: { label: 'Transfer entropy', unit: 'bits' },
  };

  function mapPalette(kind) {
    const set = MAP_PALETTES[isDark() ? 'dark' : 'light'];
    return Object.assign({}, set[kind] || set.flow, MAP_LABELS[kind] || MAP_LABELS.flow);
  }

  function hexRgb(r, g, b) {
    return '#' + [r, g, b].map((v) => Math.round(v).toString(16).padStart(2, '0')).join('');
  }

  function gradientColor(kind, norm) {
    const p = mapPalette(kind);
    const t = Math.max(0, Math.min(1, norm));
    const r = p.weak[0] + (p.strong[0] - p.weak[0]) * t;
    const g = p.weak[1] + (p.strong[1] - p.weak[1]) * t;
    const b = p.weak[2] + (p.strong[2] - p.weak[2]) * t;
    return hexRgb(r, g, b);
  }

  function gradientCss(kind) {
    const p = mapPalette(kind);
    return `linear-gradient(90deg, ${hexRgb(...p.weak)}, ${hexRgb(...p.strong)})`;
  }

  // CARTO basemaps need a key; config.js receives it from the CARTO_KEY secret at deploy time.
  const CARTO_KEY = ((window.DASHBOARD_CONFIG || {}).cartoKey || '').replace('__CARTO_KEY__', '');
  const tileUrl = () =>
    'https://{s}.basemaps.cartocdn.com/' + (isDark() ? 'dark_all' : 'light_all') + '/{z}/{x}/{y}{r}.png' +
    (CARTO_KEY ? '?key=' + encodeURIComponent(CARTO_KEY) : '');

  const map = L.map('leaflet-map', { zoomSnap: 0.5, scrollWheelZoom: false }).setView([54, 15], 4);
  const baseTiles = L.tileLayer(tileUrl(), {
    maxZoom: 18,
    attribution: '&copy; OpenStreetMap &amp; CARTO',
  }).addTo(map);
  // Let the page scroll past the map; wheel-zoom only after the user clicks into it.
  map.on('click', () => map.scrollWheelZoom.enable());
  map.on('mouseout', () => map.scrollWheelZoom.disable());

  const mapLayers = D.map_layers || { nodes: [], layers: {} };
  let mapEdgeMode = 'all';
  let mapEdgeKind = 'flow';
  const mapEdgeGroup = L.layerGroup().addTo(map);
  const mapNodeGroup = L.layerGroup().addTo(map);

  function strengthLabel(kind, value) {
    if (kind === 'flow') return Math.round(value).toLocaleString() + ' MW';
    if (kind === 'price') return 'r = ' + Number(value).toFixed(3);
    return Number(value).toFixed(4) + ' bits';
  }

  function updateMapStrengthExplain() {
    const el = document.getElementById('map-strength-explain');
    if (el && G.renderMapStrengthExplain) {
      el.innerHTML = G.renderMapStrengthExplain(mapEdgeKind);
    }
    if (S.renderMapLayerSource) {
      S.renderMapLayerSource('sources-map', mapEdgeKind, D);
    }
  }

  function renderMapEdges() {
    mapEdgeGroup.clearLayers();
    mapNodeGroup.clearLayers();

    const layer = mapLayers.layers[mapEdgeKind];
    const edges = layer ? layer[mapEdgeMode] || [] : [];
    const palette = mapPalette(mapEdgeKind);

      edges.forEach((e) => {
      const color = gradientColor(mapEdgeKind, e.norm);
      const weight = 1.5 + e.norm * 5.5;
      const belowThreshold = e.passes_threshold === false;
      const opacity = belowThreshold ? 0.25 + e.norm * 0.35 : 0.45 + e.norm * 0.5;
      const dash = mapEdgeKind === 'price' || belowThreshold ? '6 4' : null;
      const arrow = e.directed ? ' → ' : ' ↔ ';
      let thresholdNote = '';
      if (belowThreshold) {
        if (mapEdgeKind === 'te' && e.strength === 0) thresholdNote = '<br><em>No TE estimated</em>';
        else thresholdNote = '<br><em>Below threshold</em>';
      }
      L.polyline(
        [[e.lat1, e.lon1], [e.lat2, e.lon2]],
        { color, weight, opacity, dashArray: dash }
      )
        .bindTooltip(
          `<b>${e.from}${arrow}${e.to}</b><br>${zLabel(e.from)}${arrow}${zLabel(e.to)}<br>` +
            `<strong>${strengthLabel(mapEdgeKind, e.strength)}</strong>${thresholdNote}`,
          { sticky: true }
        )
        .addTo(mapEdgeGroup);
    });

    (mapLayers.nodes || []).forEach((n) => {
      L.circleMarker([n.lat, n.lon], {
        radius: 4.5,
        color: cssVar('--map-node-stroke'),
        fillColor: cssVar('--map-node-fill'),
        fillOpacity: 0.9,
        weight: 1.5,
      })
        .bindTooltip(`<b>${n.id}</b> — ${zLabel(n.id)}`, { sticky: true })
        .addTo(mapNodeGroup);
    });

    const legendEl = document.getElementById('map-gradient-legend');
    if (legendEl && palette) {
      legendEl.innerHTML =
        `<span>Weak</span>` +
        `<div class="gradient-bar" style="background:${gradientCss(mapEdgeKind)}"></div>` +
        `<span>Strong</span>` +
        `<span>(${palette.label})</span>`;
    }

    const countEl = document.getElementById('map-edge-count');
    if (countEl && layer) {
      const thresholds = mapLayers.thresholds || {};
      if (mapEdgeMode === 'all') {
        countEl.textContent = `Showing all ${edges.length} ${mapEdgeKind} connections (incl. below threshold)`;
      } else if (mapEdgeKind === 'price') {
        const floor = thresholds.price_strongest_floor ?? 0.8;
        const cut = thresholds.price_min_r ?? 0.85;
        countEl.textContent =
          `Showing ${edges.length} pairs with |r| ≥ ${floor} (${cut} = graph threshold; dashed below)`;
      } else if (mapEdgeKind === 'te') {
        countEl.textContent =
          `Showing ${edges.length} border pairs with TE ≥ ${thresholds.te_min ?? 0.003} bits (of ${layer.count} borders)`;
      } else {
        countEl.textContent = `Showing ${edges.length} validated flow connections`;
      }
    }
    updateMapStrengthExplain();
  }

  document.getElementById('map-layer-select').addEventListener('change', (ev) => {
    mapEdgeKind = ev.target.value;
    renderMapEdges();
  });

  document.querySelectorAll('.map-toggle').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.map-toggle').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      mapEdgeMode = btn.dataset.mode;
      renderMapEdges();
    });
  });

  updateMapStrengthExplain();
  renderMapEdges();

  const pricesExplain = document.getElementById('prices-strength-explain');
  if (pricesExplain && G.PAGE_STRENGTH_EXPLAIN) {
    pricesExplain.innerHTML = G.PAGE_STRENGTH_EXPLAIN.prices;
  }
  const teExplain = document.getElementById('te-strength-explain');
  if (teExplain && G.PAGE_STRENGTH_EXPLAIN) {
    teExplain.innerHTML = G.PAGE_STRENGTH_EXPLAIN.te;
  }

  document.getElementById('map-stats').innerHTML =
    `<strong>Dependency graph:</strong> ${D.graph_stats?.nodes || '—'} zones · ` +
    `${mapLayers.layers.flow?.count || 0} flow · ${mapLayers.layers.price?.count || 0} price · ` +
    `${mapLayers.layers.te?.count || 0} TE (cross-border) edges`;

  // --- Prices ---
  function renderPriceChart() {
    const canvas = document.getElementById('price-chart');
    const monthly = D.monthly_prices || {};
    const zones = Object.keys(monthly);

    if (!zones.length) {
      canvas.parentElement.innerHTML =
        '<div class="empty-state">No monthly price data available. Re-run build-dashboard.</div>';
      return;
    }

    const allMonths = [...new Set(zones.flatMap((z) => monthly[z].map((d) => d.month)))].sort();
    const labels = allMonths.map(formatMonth);
    const colors = [PAL.blue, PAL.rose, PAL.green, PAL.violet, PAL.amber];

    const datasets = zones.map((z, i) => {
      const byMonth = Object.fromEntries(monthly[z].map((d) => [d.month, d.price]));
      return {
        label: zChartLabel(z),
        data: allMonths.map((m) => byMonth[m] ?? null),
        borderColor: colors[i % colors.length],
        backgroundColor: colors[i % colors.length] + '22',
        borderWidth: 2,
        pointRadius: 3,
        tension: 0.25,
        spanGaps: true,
      };
    });

    if (charts.price) {
      charts.price.data.labels = labels;
      charts.price.data.datasets = datasets;
      charts.price.update();
      charts.price.resize();
      return;
    }

    charts.price = new Chart(canvas, {
      type: 'line',
      data: { labels, datasets },
      options: {
        ...chartDefaults,
        plugins: {
          ...chartDefaults.plugins,
          title: {
            display: true,
            text: 'Monthly average day-ahead price by bidding zone',
            font: { size: 13, weight: '600' },
            padding: { bottom: 12 },
          },
        },
      },
    });
  }

  const priceBody = document.querySelector('#price-summary-table tbody');
  (D.price_summaries || []).forEach((r) => {
    const tr = document.createElement('tr');
    tr.innerHTML =
      `<td>${zCell(r.zone)}</td>` +
      `<td class="num">${r.mean}</td>` +
      `<td class="num">${r.min}</td>` +
      `<td class="num">${r.max}</td>` +
      `<td class="num">${r.hours.toLocaleString()}</td>`;
    priceBody.appendChild(tr);
  });
  if (!D.price_summaries?.length) {
    priceBody.innerHTML = '<tr><td colspan="5" class="muted">No price summary available</td></tr>';
  }

  // --- Seasonality ---
  const hodProfiles = D.seasonality?.hourly_profiles || {};
  const hodZones = Object.keys(hodProfiles).sort();
  const hodSelect = document.getElementById('hod-zone-select');
  hodZones.forEach((z) => {
    const opt = document.createElement('option');
    opt.value = z;
    opt.textContent = zChartLabel(z);
    hodSelect.appendChild(opt);
  });
  if (!hodZones.length) {
    hodSelect.innerHTML = '<option>No profile data</option>';
  }

  function renderSeasonalityCharts() {
    renderHodChart();
    renderQuarterChart();
    renderMonthSeasonChart();
  }

  function renderQuarterChart() {
    const canvas = document.getElementById('quarter-chart');
    const zone = hodSelect.value;
    const profiles = D.seasonality?.quarterly_profiles || {};
    const labels = D.seasonality?.quarter_labels || ['Q1', 'Q2', 'Q3', 'Q4'];
    const data = profiles[zone] || [];

    if (charts.quarter) {
      charts.quarter.data.datasets[0].data = data;
      charts.quarter.data.datasets[0].label = zone;
      charts.quarter.options.plugins.title.text = `Quarterly average — ${zChartLabel(zone)}`;
      charts.quarter.update();
      charts.quarter.resize();
      return;
    }

    charts.quarter = new Chart(canvas, {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          label: zone,
          data,
          backgroundColor: alpha(PAL.blue, 0.7),
          borderColor: PAL.blue,
          borderWidth: 1,
        }],
      },
      options: {
        ...chartDefaults,
        plugins: {
          ...chartDefaults.plugins,
          legend: { display: false },
          title: {
            display: true,
            text: `Quarterly average — ${zChartLabel(zone)}`,
            font: { size: 12, weight: '600' },
          },
        },
      },
    });
  }

  function renderMonthSeasonChart() {
    const canvas = document.getElementById('month-season-chart');
    const zone = hodSelect.value;
    const profiles = D.seasonality?.monthly_profiles || {};
    const labels = D.seasonality?.calendar_month_labels || MONTH_NAMES;
    const data = profiles[zone] || [];

    if (charts.monthSeason) {
      charts.monthSeason.data.datasets[0].data = data;
      charts.monthSeason.data.datasets[0].label = zone;
      charts.monthSeason.options.plugins.title.text = `Calendar-month average — ${zChartLabel(zone)}`;
      charts.monthSeason.update();
      charts.monthSeason.resize();
      return;
    }

    charts.monthSeason = new Chart(canvas, {
      type: 'line',
      data: {
        labels,
        datasets: [{
          label: zone,
          data,
          borderColor: PAL.amber,
          backgroundColor: alpha(PAL.amber, 0.14),
          fill: true,
          borderWidth: 2,
          tension: 0.3,
        }],
      },
      options: {
        ...chartDefaults,
        plugins: {
          ...chartDefaults.plugins,
          title: {
            display: true,
            text: `Calendar-month average — ${zChartLabel(zone)}`,
            font: { size: 12, weight: '600' },
          },
        },
      },
    });
  }

  function renderHodChart() {
    const canvas = document.getElementById('hod-chart');
    const zone = hodSelect.value;
    const profile = hodProfiles[zone] || [];
    const labels = [...Array(24).keys()].map((h) => `${String(h).padStart(2, '0')}:00 UTC`);

    if (charts.hod) {
      charts.hod.data.labels = labels;
      charts.hod.data.datasets[0].label = zone;
      charts.hod.data.datasets[0].data = profile;
      charts.hod.options.plugins.title.text = `Average price by hour of day — ${zChartLabel(zone)}`;
      charts.hod.update();
      charts.hod.resize();
      return;
    }

    charts.hod = new Chart(canvas, {
      type: 'line',
      data: {
        labels,
        datasets: [{
          label: zone,
          data: profile,
          borderColor: PAL.blue,
          backgroundColor: alpha(PAL.blue, 0.14),
          fill: true,
          borderWidth: 2,
          pointRadius: 2,
          tension: 0.3,
        }],
      },
      options: {
        ...chartDefaults,
        plugins: {
          ...chartDefaults.plugins,
          title: {
            display: true,
            text: `Average price by hour of day — ${zChartLabel(zone)}`,
            font: { size: 13, weight: '600' },
            padding: { bottom: 12 },
          },
        },
      },
    });
  }

  hodSelect.addEventListener('change', () => {
    if (document.getElementById('panel-seasonality').classList.contains('active')) {
      renderSeasonalityCharts();
    }
  });

  const hodBody = document.querySelector('#hod-table tbody');
  (D.seasonality?.top_hod_strength || []).forEach((r) => {
    const tr = document.createElement('tr');
    tr.innerHTML =
      `<td>${zCell(r.zone)}</td>` +
      `<td class="num">${(r.hod_strength * 100).toFixed(1)}%</td>` +
      `<td class="num">${((r.dow_strength || 0) * 100).toFixed(1)}%</td>` +
      `<td class="num">${((r.moy_strength || 0) * 100).toFixed(1)}%</td>` +
      `<td class="num">${r.quarter_spread ?? '—'}</td>` +
      `<td class="num">${r.residual_std}</td>`;
    hodBody.appendChild(tr);
  });

  const loadBody = document.querySelector('#load-season-table tbody');
  const loadRows = D.load_seasonality?.top_moy_strength || [];
  if (!loadRows.length) {
    loadBody.innerHTML = '<tr><td colspan="4" class="muted">Run: energy-collect decompose-seasonality --all</td></tr>';
  } else {
    loadRows.forEach((r) => {
      const tr = document.createElement('tr');
      tr.innerHTML =
        `<td>${zCell(r.zone)}</td>` +
        `<td class="num">${((r.moy_strength || 0) * 100).toFixed(1)}%</td>` +
        `<td class="num">${r.quarter_spread ?? '—'}</td>` +
        `<td class="num">${r.mean ?? '—'}</td>`;
      loadBody.appendChild(tr);
    });
  }

  // --- Transfer entropy ---
  const teStats = document.getElementById('te-stats');
  teStats.innerHTML =
    `<div class="stat-card"><div class="value">${D.te_border_count || 0}</div><div class="label">Cross-border TE edges</div></div>` +
    `<div class="stat-card"><div class="value">${(D.te_top_value || 0).toFixed(3)}</div><div class="label">Strongest TE (bits)</div></div>` +
    `<div class="stat-card"><div class="value">${D.seasonality?.zones || 0}</div><div class="label">Zones in TE analysis</div></div>`;

  const teBody = document.querySelector('#te-table tbody');
  const teEdges = D.te_border_edges || D.te_edges || [];
  if (!teEdges.length) {
    teBody.innerHTML = '<tr><td colspan="5" class="muted">No transfer entropy edges above threshold</td></tr>';
  } else {
    teEdges.forEach((e) => {
      const tr = document.createElement('tr');
      tr.innerHTML =
        `<td>${zCell(e.from)}</td>` +
        `<td class="arrow">→</td>` +
        `<td>${zCell(e.to)}</td>` +
        `<td class="num">${e.te.toFixed ? e.te.toFixed(4) : e.te}</td>` +
        `<td class="muted">${teInterpretation(Number(e.te))}</td>`;
      teBody.appendChild(tr);
    });
  }

  // --- Price vs flow mismatch ---
  const M = D.meeting || {};
  const mm = M.mismatch || {};
  const mmCounts = mm.counts || {};
  const mismatchStats = document.getElementById('mismatch-stats');
  if (mismatchStats) {
    mismatchStats.innerHTML =
      `<div class="stat-card"><div class="value">${mm.n_borders || 0}</div><div class="label">Borders classified</div></div>` +
      `<div class="stat-card"><div class="value">${mmCounts.congested_trade || 0}</div><div class="label">Congested trade</div></div>` +
      `<div class="stat-card"><div class="value">${mmCounts.paper_coupling || 0}</div><div class="label">Paper coupling</div></div>` +
      `<div class="stat-card"><div class="value">${mmCounts.aligned_strong || 0}</div><div class="label">Aligned strong</div></div>`;
  }

  function mismatchBadge(cls, label) {
    return `<span class="mismatch-badge mismatch-${cls}">${label || cls}</span>`;
  }

  function fillMismatchTable(tbodySelector, rows) {
    const body = document.querySelector(tbodySelector + ' tbody');
    if (!body) return;
    if (!rows || !rows.length) {
      body.innerHTML = '<tr><td colspan="5" class="muted">Run: energy-collect analyze-meeting --year 2025</td></tr>';
      return;
    }
    body.innerHTML = '';
    rows.forEach((r) => {
      const tr = document.createElement('tr');
      const rStr = r.pearson_r == null ? '—' : Number(r.pearson_r).toFixed(3);
      tr.innerHTML =
        `<td>${zCell(r.a)} – ${zCell(r.b)}</td>` +
        `<td class="num">${Number(r.mean_abs_mw).toLocaleString()}</td>` +
        `<td class="num">${rStr}</td>` +
        `<td class="num">${Number(r.te_max).toFixed(4)}</td>` +
        `<td>${mismatchBadge(r.class, r.class_label || r.class)}</td>`;
      body.appendChild(tr);
    });
  }

  const frEs = mm.fr_es;
  const frEl = document.getElementById('fr-es-callout');
  if (frEl) {
    if (frEs) {
      frEl.className = 'callout-box';
      frEl.innerHTML =
        `<strong>France – Spain example.</strong> Mean |flow| ${Number(frEs.mean_abs_mw).toLocaleString()} MW, ` +
        `Pearson r = ${frEs.pearson_r == null ? '—' : Number(frEs.pearson_r).toFixed(3)}, ` +
        `TE max = ${Number(frEs.te_max).toFixed(4)} bits → ${mismatchBadge(frEs.class, frEs.class_label)}.`;
    } else {
      frEl.innerHTML = '';
    }
  }
  fillMismatchTable('#mismatch-highlight-table', mm.highlights || []);
  fillMismatchTable('#mismatch-table', mm.borders || []);

  const interp = M.interpretations || {};
  const mismatchExplain = document.getElementById('mismatch-explain');
  if (mismatchExplain) {
    mismatchExplain.innerHTML =
      explainCard('Why MW and prices are not the same thing', interp.mismatch_mechanism) +
      explainCard('France–Spain vs Spain–Portugal', interp.fr_es) +
      explainCard('Paper coupling', interp.paper_coupling) +
      explainCard('When both layers agree', interp.aligned);
  }

  function explainCard(title, body) {
    if (!body) return '';
    return '<article class="explain-card"><h3>' + title + '</h3><p>' + body + '</p></article>';
  }

  const SCATTER_COLORS = {
    congested_trade: PAL.orange,
    paper_coupling: PAL.blue,
    aligned_strong: PAL.green,
    informational: PAL.violet,
    weak: PAL.slate,
  };
  const SCATTER_LABELS = {
    congested_trade: 'Congested trade',
    paper_coupling: 'Paper coupling',
    aligned_strong: 'Aligned strong',
    informational: 'Informational',
    weak: 'Weak',
  };

  function renderMismatchScatter() {
    const canvas = document.getElementById('mismatch-scatter');
    if (!canvas) return;
    const points = M.mismatch_scatter || mm.borders || [];
    const byClass = {};
    points.forEach((p) => {
      const cls = p.class || 'weak';
      if (!byClass[cls]) byClass[cls] = [];
      const x = p.x != null ? p.x : p.pearson_r;
      const y = p.y != null ? p.y : p.mean_abs_mw;
      if (x == null || y == null) return;
      byClass[cls].push({ x, y, a: p.a, b: p.b });
    });
    const datasets = Object.keys(byClass).map((cls) => ({
      label: SCATTER_LABELS[cls] || cls,
      data: byClass[cls],
      backgroundColor: SCATTER_COLORS[cls] || PAL.slate,
      borderColor: SCATTER_COLORS[cls] || PAL.slate,
    }));
    const options = {
      ...chartDefaults,
      plugins: {
        ...chartDefaults.plugins,
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const d = ctx.raw;
              return `${d.a}–${d.b}: r=${Number(d.x).toFixed(3)}, |MW|=${Math.round(d.y)}`;
            },
          },
        },
        title: {
          display: true,
          text: 'High and to the right = coupled and heavily used; high and left = congested trade',
          font: { size: 12, weight: '600' },
        },
      },
      scales: {
        x: {
          title: { display: true, text: 'Pearson r (hourly day-ahead prices)', font: { size: 11 } },
          min: 0,
          max: 1,
          grid: { color: GRID() },
        },
        y: {
          title: { display: true, text: 'Mean |physical flow| (MW)', font: { size: 11 } },
          grid: { color: GRID() },
        },
      },
    };
    if (charts.mismatchScatter) {
      charts.mismatchScatter.data.datasets = datasets;
      charts.mismatchScatter.update();
      charts.mismatchScatter.resize();
      return;
    }
    charts.mismatchScatter = new Chart(canvas, { type: 'scatter', data: { datasets }, options });
  }

  // --- TE regimes ---
  const regimes = M.te_regimes || {};
  const nested = M.nested_te || {};
  const regimeStats = document.getElementById('regime-stats');
  if (regimeStats) {
    regimeStats.innerHTML =
      `<div class="stat-card"><div class="value">${(regimes.hod && regimes.hod.reversal_count) || 0}</div><div class="label">HOD reversals</div></div>` +
      `<div class="stat-card"><div class="value">${(regimes.season && regimes.season.reversal_count) || 0}</div><div class="label">Season reversals</div></div>` +
      `<div class="stat-card"><div class="value">${nested.leader_agreement_year_vs_month_avg || 0}/${nested.pair_count || 0}</div><div class="label">Year vs month-avg leader</div></div>` +
      `<div class="stat-card"><div class="value">${nested.weeks_used || 0}</div><div class="label">ISO weeks used</div></div>`;
  }

  const regimeExplain = document.getElementById('regime-explain');
  if (regimeExplain) {
    regimeExplain.innerHTML =
      explainCard('Why a yearly TE arrow is not enough', interp.te_regimes) +
      explainCard('Season reversals (clearest signal)', interp.te_season) +
      explainCard('Nested averages vs the year graph', interp.te_nested);
  }

  const regimeCharts = M.regime_charts || {};
  const LINE_PALETTE = [PAL.blue, PAL.rose, PAL.green, PAL.violet, PAL.amber, PAL.teal];

  function currentRegimeKey() {
    const sel = document.getElementById('regime-select');
    return sel ? sel.value : 'hod';
  }

  function fillRegimePairSelect() {
    const sel = document.getElementById('regime-pair-select');
    if (!sel) return;
    const pack = regimeCharts[currentRegimeKey()] || { series: [] };
    const prev = sel.value;
    sel.innerHTML = '';
    (pack.series || []).forEach((s, i) => {
      const opt = document.createElement('option');
      opt.value = String(i);
      opt.textContent = (s.a || '') + ' – ' + (s.b || '');
      sel.appendChild(opt);
    });
    if (prev && [...sel.options].some((o) => o.value === prev)) sel.value = prev;
  }

  function lineOpts(title, yText) {
    return {
      ...chartDefaults,
      plugins: {
        ...chartDefaults.plugins,
        title: { display: true, text: title, font: { size: 12, weight: '600' } },
      },
      scales: {
        x: { grid: { display: false }, ticks: { maxRotation: 45, font: { size: 10 } } },
        y: {
          title: { display: true, text: yText, font: { size: 11 } },
          grid: { color: GRID() },
        },
      },
    };
  }

  function upsertLineChart(key, canvas, labels, datasets, title, yText) {
    if (!canvas) return;
    if (charts[key]) {
      charts[key].data.labels = labels;
      charts[key].data.datasets = datasets;
      charts[key].options.plugins.title.text = title;
      charts[key].update();
      charts[key].resize();
      return;
    }
    charts[key] = new Chart(canvas, {
      type: 'line',
      data: { labels, datasets },
      options: lineOpts(title, yText),
    });
  }

  function renderRegimeLineCharts() {
    fillRegimePairSelect();
    const pack = regimeCharts[currentRegimeKey()] || { labels: [], series: [] };
    const labels = pack.labels || [];
    const series = pack.series || [];
    const pairSel = document.getElementById('regime-pair-select');
    const idx = pairSel ? parseInt(pairSel.value || '0', 10) : 0;
    const one = series[idx] || series[0];
    if (one) {
      upsertLineChart(
        'tePair',
        document.getElementById('te-pair-line-chart'),
        labels,
        [
          {
            label: one.a + ' → ' + one.b,
            data: one.te_a_to_b,
            borderColor: PAL.blue,
            backgroundColor: alpha(PAL.blue, 0.14),
            tension: 0.25,
            spanGaps: true,
            pointRadius: 2,
          },
          {
            label: one.b + ' → ' + one.a,
            data: one.te_b_to_a,
            borderColor: PAL.rose,
            backgroundColor: alpha(PAL.rose, 0.14),
            tension: 0.25,
            spanGaps: true,
            pointRadius: 2,
          },
        ],
        'Transfer entropy both ways — ' + one.a + '–' + one.b,
        'TE (bits)'
      );
    }
    const netSets = series.slice(0, 6).map((s, i) => ({
      label: s.a + '–' + s.b + ' net',
      data: s.net,
      borderColor: LINE_PALETTE[i % LINE_PALETTE.length],
      tension: 0.25,
      spanGaps: true,
      pointRadius: 2,
      fill: false,
    }));
    upsertLineChart(
      'teNet',
      document.getElementById('te-net-line-chart'),
      labels,
      netSets,
      'Net TE (positive = first zone leads)',
      'Net TE (bits)'
    );
  }

  function renderReversalTable() {
    const key = currentRegimeKey();
    const payload = regimes[key] || {};
    const body = document.querySelector('#reversal-table tbody');
    if (!body) return;
    const rows = payload.reversals || [];
    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="4" class="muted">No reversals (or run analyze-meeting)</td></tr>';
      return;
    }
    body.innerHTML = '';
    rows.forEach((r) => {
      const tr = document.createElement('tr');
      tr.innerHTML =
        `<td>${zCell(r.a)} – ${zCell(r.b)}</td>` +
        `<td class="muted">${(r.a_leads_in || []).join(', ')}</td>` +
        `<td class="muted">${(r.b_leads_in || []).join(', ')}</td>` +
        `<td class="num">${r.n_bins_used}</td>`;
      body.appendChild(tr);
    });
  }
  const regimeSelect = document.getElementById('regime-select');
  if (regimeSelect) {
    regimeSelect.addEventListener('change', () => {
      renderReversalTable();
      renderRegimeLineCharts();
    });
    renderReversalTable();
  }
  const regimePairSelect = document.getElementById('regime-pair-select');
  if (regimePairSelect) {
    regimePairSelect.addEventListener('change', renderRegimeLineCharts);
  }

  const nestedBody = document.querySelector('#nested-te-table tbody');
  if (nestedBody) {
    const scale = nested.scale_table || [];
    if (!scale.length) {
      nestedBody.innerHTML = '<tr><td colspan="7" class="muted">Run analyze-meeting</td></tr>';
    } else {
      scale.forEach((r) => {
        const tr = document.createElement('tr');
        const fmt = (v) => (v == null || Number.isNaN(v) ? '—' : Number(v).toFixed(4));
        tr.innerHTML =
          `<td>${zCell(r.a)} – ${zCell(r.b)}</td>` +
          `<td class="num">${fmt(r.year_a_to_b)}</td>` +
          `<td class="num">${fmt(r.year_b_to_a)}</td>` +
          `<td class="num">${fmt(r.month_avg_a_to_b)}</td>` +
          `<td class="num">${fmt(r.week_avg_a_to_b)}</td>` +
          `<td class="num">${fmt(r.hod_avg_a_to_b)}</td>` +
          `<td>${r.leader_agrees_month ? 'yes' : 'no'}</td>`;
        nestedBody.appendChild(tr);
      });
    }
  }

  function renderNestedTeChart() {
    const canvas = document.getElementById('nested-te-chart');
    if (!canvas) return;
    const scale = (nested.scale_table || []).slice(0, 6);
    const labels = ['Year', 'Month avg', 'Week avg', 'HOD avg'];
    const datasets = scale.map((r, i) => ({
      label: r.a + '→' + r.b,
      data: [r.year_a_to_b, r.month_avg_a_to_b, r.week_avg_a_to_b, r.hod_avg_a_to_b],
      borderColor: LINE_PALETTE[i % LINE_PALETTE.length],
      tension: 0.25,
      spanGaps: true,
      pointRadius: 3,
      fill: false,
    }));
    upsertLineChart(
      'nestedTe',
      canvas,
      labels,
      datasets,
      'Same pair, four time scales (A→B)',
      'TE (bits)'
    );
  }

  function renderNestedHodChart() {
    const canvas = document.getElementById('nested-hod-line-chart');
    if (!canvas) return;
    const scale = (nested.scale_table || []).filter((r) => (r.hod_net_series || []).length).slice(0, 5);
    const labels = [...Array(24).keys()].map((h) => String(h).padStart(2, '0') + ':00');
    const datasets = scale.map((r, i) => ({
      label: r.a + '–' + r.b,
      data: r.hod_net_series,
      borderColor: LINE_PALETTE[i % LINE_PALETTE.length],
      tension: 0.25,
      spanGaps: true,
      pointRadius: 2,
      fill: false,
    }));
    upsertLineChart(
      'nestedHod',
      canvas,
      labels,
      datasets,
      'Hour-of-day net TE on nested corridors',
      'Net TE (bits)'
    );
  }

  // --- Network & grid ---
  const structure = M.structure || {};
  const grid = M.grid || {};
  const netStats = document.getElementById('network-stats');
  if (netStats) {
    netStats.innerHTML =
      `<div class="stat-card"><div class="value">${(grid.osm_lines || 0).toLocaleString()}</div><div class="label">OSM AC lines</div></div>` +
      `<div class="stat-card"><div class="value">${(grid.osm_substations || 0).toLocaleString()}</div><div class="label">Substations</div></div>` +
      `<div class="stat-card"><div class="value">${grid.osm_hvdc_links || 0}</div><div class="label">HVDC links</div></div>` +
      `<div class="stat-card"><div class="value">${(structure.price_communities || []).length}</div><div class="label">Price communities (size&gt;1)</div></div>`;
  }
  const overlapEl = document.getElementById('hub-overlap');
  if (overlapEl && structure.hub_overlap) {
    const o = structure.hub_overlap;
    overlapEl.textContent =
      `Top-${o.top_k || 8} hub overlap — all three layers: ${(o.all_three || []).join(', ') || 'none'}. ` +
      `Flow only: ${(o.flow_only || []).join(', ') || '—'}. TE only: ${(o.te_only || []).join(', ') || '—'}.`;
  }

  function fillHubTable(id, rows) {
    const body = document.querySelector('#' + id + ' tbody');
    if (!body) return;
    body.innerHTML = '';
    (rows || []).slice(0, 10).forEach((r) => {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${zCell(r.zone)}</td><td class="num">${r.strength}</td><td class="num">${r.degree}</td>`;
      body.appendChild(tr);
    });
  }
  fillHubTable('hub-price-table', (structure.hubs || {}).price);
  fillHubTable('hub-flow-table', (structure.hubs || {}).flow);
  fillHubTable('hub-te-table', (structure.hubs || {}).te);

  const voltBody = document.querySelector('#voltage-table tbody');
  if (voltBody) {
    (grid.voltage_histogram || []).forEach((r) => {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${r.voltage_kv} kV</td><td class="num">${r.lines}</td>`;
      voltBody.appendChild(tr);
    });
  }

  function renderNetworkCharts() {
    const subCanvas = document.getElementById('substation-chart');
    const gemCanvas = document.getElementById('gem-type-chart');
    const subRows = grid.substations_by_country || [];
    if (subCanvas && subRows.length) {
      const labels = subRows.map((r) => r.country);
      const data = subRows.map((r) => r.substations);
      if (charts.substations) {
        charts.substations.data.labels = labels;
        charts.substations.data.datasets[0].data = data;
        charts.substations.update();
        charts.substations.resize();
      } else {
        charts.substations = new Chart(subCanvas, {
          type: 'bar',
          data: { labels, datasets: [{ label: 'Substations', data, backgroundColor: alpha(PAL.blue, 0.7) }] },
          options: {
            ...chartDefaults,
            plugins: { ...chartDefaults.plugins, legend: { display: false } },
            scales: {
              ...chartDefaults.scales,
              y: { ...chartDefaults.scales.y, title: { display: true, text: 'Count', font: { size: 11 } } },
            },
          },
        });
      }
    }
    const gemRows = grid.gem_operating_capacity_by_type || [];
    if (gemCanvas && gemRows.length) {
      const labels = gemRows.map((r) => r.type);
      const data = gemRows.map((r) => r.capacity_mw);
      if (charts.gemType) {
        charts.gemType.data.labels = labels;
        charts.gemType.data.datasets[0].data = data;
        charts.gemType.update();
        charts.gemType.resize();
      } else {
        charts.gemType = new Chart(gemCanvas, {
          type: 'bar',
          data: { labels, datasets: [{ label: 'MW', data, backgroundColor: alpha(PAL.green, 0.7) }] },
          options: {
            ...chartDefaults,
            indexAxis: 'y',
            plugins: { ...chartDefaults.plugins, legend: { display: false } },
            scales: {
              x: { title: { display: true, text: 'MW', font: { size: 11 } }, grid: { color: GRID() } },
              y: { grid: { display: false }, ticks: { font: { size: 10 } } },
            },
          },
        });
      }
    }
  }

  // --- Coverage ---
  const covStats = document.getElementById('coverage-stats');
  covStats.innerHTML =
    `<div class="stat-card"><div class="value">${D.target_zones || 45}</div><div class="label">Target bidding zones</div></div>` +
    `<div class="stat-card"><div class="value">${D.zones_with_prices || '—'}</div><div class="label">With full-year prices</div></div>` +
    `<div class="stat-card"><div class="value">${(D.coverage_gaps || []).length}</div><div class="label">Datasets with gaps</div></div>`;

  const gapBody = document.querySelector('#gap-table tbody');
  (D.coverage_gaps || []).forEach((r) => {
    const tr = document.createElement('tr');
    const docHint = r.doc ? `<br><small class="muted">${r.doc}</small>` : '';
    tr.innerHTML =
      `<td><strong>${r.label || r.dataset}</strong>${docHint}</td>` +
      `<td class="num">${r.present ?? '—'}</td>` +
      `<td class="missing-zones">${formatMissingZones(r.missing)}</td>`;
    gapBody.appendChild(tr);
  });

  // --- Glossaries per panel ---

  // ---------------------------------------------------------------- RQ1-RQ3
  const CM = D.comovement || {};

  function pct(x, digits) {
    return x === null || x === undefined ? '—' : (100 * x).toFixed(digits === undefined ? 1 : digits) + '%';
  }
  function num(x, digits) {
    if (x === null || x === undefined) return '—';
    // Round half away from zero so the text matches the rendered figures,
    // which use Python's rounding rather than JS float truncation.
    const d = digits === undefined ? 2 : digits;
    const p = Math.pow(10, d);
    const v = Math.sign(x) * Math.round(Math.abs(x) * p + 1e-9) / p;
    return v.toFixed(d);
  }
  function esc(text) {
    return String(text === null || text === undefined ? '' : text)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
  function statCard(value, label) {
    return '<div class="stat-card"><div class="value">' + value + '</div><div class="label">' + label + '</div></div>';
  }
  function answerBox(id, rq, text) {
    const el = document.getElementById(id);
    if (!el) return;
    if (!text) {
      el.innerHTML = '<h3>' + rq + '</h3><p class="muted">Run: <code>energy-collect analyze-comovement --year 2025</code></p>';
      return;
    }
    el.innerHTML = '<h3>' + rq + ' — answer</h3><p>' + text + '</p>';
  }
  function fillRows(selector, rows, emptyCols) {
    const body = document.querySelector(selector + ' tbody');
    if (!body) return null;
    if (!rows || !rows.length) {
      body.innerHTML = '<tr><td colspan="' + emptyCols + '" class="muted">Run: energy-collect analyze-comovement --year 2025</td></tr>';
      return null;
    }
    return body;
  }
  function zoneList(codes) {
    return '<div class="zone-list">' + (codes || []).map((c) => '<span title="' + zLabel(c) + '">' + c + '</span>').join('') + '</div>';
  }
  function borderCell(a, b) {
    return '<div class="zone-cell"><span class="zone-code">' + a + ' – ' + b + '</span><small>' + zLabel(a) + ' – ' + zLabel(b) + '</small></div>';
  }

  // --- RQ1 ---
  function renderRq1() {
    const rq1 = CM.rq1 || {};
    const sp = rq1.spectrum || {};
    const va = (rq1.variance || {}).residual || {};
    const lv = (rq1.variance || {}).levels || {};
    answerBox('rq1-answer', 'RQ1', (CM.findings || {}).rq1);

    const stats = document.getElementById('rq1-stats');
    if (stats) {
      stats.innerHTML =
        statCard(pct(va.market, 0), 'Europe-wide mode (shocks)') +
        statCard(pct(va.cluster, 0), 'Cluster-specific modes') +
        statCard(sp.cluster_dimensions ?? '—', 'Supported cluster dimensions') +
        statCard((sp.k_significant_95 ?? '—') + ' / ' + (sp.k_significant_mp ?? '—'), 'Modes: surrogate / MP bound');
    }

    const varCanvas = document.getElementById('rq1-variance');
    if (varCanvas && va.market !== undefined) {
      if (charts.rq1Variance) charts.rq1Variance.destroy();
      charts.rq1Variance = new Chart(varCanvas, {
        type: 'bar',
        data: {
          labels: ['Deseasonalised (shocks)', 'Raw levels'],
          datasets: [
            { label: 'Europe-wide mode', data: [100 * va.market, 100 * lv.market], backgroundColor: PAL.blue },
            { label: 'Cluster modes', data: [100 * va.cluster, 100 * lv.cluster], backgroundColor: PAL.cyan },
            { label: 'Noise bulk', data: [100 * va.noise, 100 * lv.noise], backgroundColor: MUTED() },
          ],
        },
        options: {
          indexAxis: 'y',
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { position: 'bottom', labels: { boxWidth: 12, padding: 12, font: { size: 11 } } },
            tooltip: { callbacks: { label: (c) => c.dataset.label + ': ' + c.parsed.x.toFixed(1) + '%' } },
          },
          scales: {
            x: { stacked: true, max: 100, title: { display: true, text: '% of total variance' }, grid: { color: GRID() } },
            y: { stacked: true, grid: { display: false } },
          },
        },
      });
    }

    const explain = document.getElementById('rq1-explain');
    if (explain) {
      const gap = va.market !== undefined ? (100 * (lv.market - va.market)).toFixed(0) : '—';
      explain.innerHTML =
        explainCard(
          'Why two bars',
          'Raw prices share a daily and seasonal shape everywhere in Europe, so correlating levels counts that calendar twice. Removing hour-of-day, day-of-week and month effects first leaves the genuine shared shocks. The ' + gap + '-point gap between the bars is the size of that artefact.'
        ) +
        explainCard(
          'Why a surrogate null',
          'Electricity prices are strongly autocorrelated (mean AR(1) = ' + num(sp.mean_ar1) + '), so ' + (sp.hours || '—') + ' hours behave like only about ' + num(sp.n_effective, 0) + ' independent observations. A textbook Marchenko–Pastur bound on the raw hour count would call almost every eigenvalue significant. Phase-randomised surrogates keep each zone’s own spectrum and destroy only the cross-zone coupling, so the band they produce is the honest one.'
        ) +
        explainCard(
          'Modes are not blocs',
          'A supported eigenvalue is a direction of cluster structure, not a cluster. ' + (sp.cluster_dimensions ?? '—') + ' dimensions can resolve more than ' + ((sp.cluster_dimensions ?? 0) + 1) + ' groups — RQ2 picks the actual number of blocs on the silhouette curve.'
        );
    }

    const specCanvas = document.getElementById('rq1-spectrum');
    if (specCanvas && (sp.eigenvalues || []).length) {
      if (charts.rq1Spectrum) charts.rq1Spectrum.destroy();
      const labels = sp.eigenvalues.map((_, i) => 'λ' + (i + 1));
      charts.rq1Spectrum = new Chart(specCanvas, {
        type: 'bar',
        data: {
          labels,
          datasets: [
            {
              type: 'bar',
              label: 'Observed eigenvalue',
              data: sp.eigenvalues,
              backgroundColor: sp.eigenvalues.map((v, i) => (i < (sp.k_significant_95 || 0) ? PAL.blue : MUTED())),
            },
            { type: 'line', label: 'Surrogate 95th percentile', data: sp.null_q95, borderColor: PAL.rose, borderWidth: 2, pointRadius: 2, fill: false },
            { type: 'line', label: 'Surrogate mean', data: sp.null_mean, borderColor: PAL.slate, borderWidth: 1, borderDash: [4, 3], pointRadius: 0, fill: false },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { position: 'bottom', labels: { boxWidth: 12, padding: 12, font: { size: 11 } } },
            tooltip: { mode: 'index', intersect: false },
          },
          scales: {
            x: { grid: { display: false } },
            y: { type: 'logarithmic', title: { display: true, text: 'Eigenvalue (log scale)' }, grid: { color: GRID() } },
          },
        },
      });
    }

    const body = fillRows('#rq1-modes-table', rq1.modes, 4);
    if (body) {
      body.innerHTML = rq1.modes
        .map((m) => {
          const tag = m.significant
            ? '<span class="verdict verdict-stable">supported</span>'
            : '<span class="verdict verdict-reorg">noise</span>';
          const kind = m.mode === 1 && m.all_same_sign ? ' <small>(all loadings same sign → true market mode)</small>' : '';
          const loads = m.loadings
            .map((l) => '<span title="' + zLabel(l.zone) + '">' + l.zone + ' ' + (l.loading > 0 ? '+' : '') + l.loading.toFixed(2) + '</span>')
            .join('');
          return (
            '<tr><td>Mode ' + m.mode + kind + '</td><td>' + pct(m.explained) + '</td><td>' + tag +
            '</td><td><div class="zone-list">' + loads + '</div></td></tr>'
          );
        })
        .join('');
    }
  }

  // --- RQ2 ---
  function renderRq2() {
    const rq2 = CM.rq2 || {};
    const sum = rq2.summary || {};
    answerBox('rq2-answer', 'RQ2', (CM.findings || {}).rq2);

    const stats = document.getElementById('rq2-stats');
    if (stats) {
      const range = sum.market_mode_range || [];
      stats.innerHTML =
        statCard(rq2.k ?? '—', 'Blocs in the partition') +
        statCard(num(sum.mean_ari), 'Mean ARI vs full year') +
        statCard((sum.n_reorganised ?? '—') + ' / ' + (sum.n_strata ?? '—'), 'Strata that reorganise') +
        statCard(range.length ? pct(range[0], 0) + '–' + pct(range[1], 0) : '—', 'Europe-wide mode range');
    }

    const clusterBody = fillRows('#rq2-clusters-table', rq2.clusters, 3);
    if (clusterBody) {
      clusterBody.innerHTML = rq2.clusters
        .map((c) => '<tr><td><strong>' + c.name + '</strong></td><td>' + zoneList(c.members) + '</td><td>' + c.size + '</td></tr>')
        .join('');
    }

    const strata = (rq2.seasons || []).concat(rq2.hour_blocks || [], rq2.season_hour || []);
    const ariCanvas = document.getElementById('rq2-ari');
    if (ariCanvas && strata.length) {
      if (charts.rq2Ari) charts.rq2Ari.destroy();
      charts.rq2Ari = new Chart(ariCanvas, {
        data: {
          labels: strata.map((r) => r.label),
          datasets: [
            {
              type: 'bar',
              label: 'Observed ARI',
              data: strata.map((r) => r.ari),
              backgroundColor: strata.map((r) => (r.reorganised ? PAL.rose : PAL.blue)),
            },
            {
              type: 'line',
              label: 'Null 5th percentile (reorganisation threshold)',
              data: strata.map((r) => r.null_p05),
              borderColor: PAL.amber,
              borderWidth: 2,
              borderDash: [5, 4],
              pointRadius: 2,
              fill: false,
            },
            {
              type: 'line',
              label: 'Null median (expected from sample size alone)',
              data: strata.map((r) => r.null_median),
              borderColor: PAL.slate,
              borderWidth: 1,
              pointRadius: 0,
              fill: false,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { position: 'bottom', labels: { boxWidth: 12, padding: 12, font: { size: 11 } } }, tooltip: { mode: 'index', intersect: false } },
          scales: {
            x: { grid: { display: false }, ticks: { maxRotation: 70, minRotation: 45, font: { size: 9 } } },
            y: { min: 0, max: 1, title: { display: true, text: 'Adjusted Rand Index' }, grid: { color: GRID() } },
          },
        },
      });
    }

    const marketCanvas = document.getElementById('rq2-market');
    if (marketCanvas && strata.length) {
      if (charts.rq2Market) charts.rq2Market.destroy();
      charts.rq2Market = new Chart(marketCanvas, {
        type: 'bar',
        data: {
          labels: strata.map((r) => r.label),
          datasets: [{ label: 'Share of variance in the Europe-wide mode', data: strata.map((r) => 100 * r.market_mode_share), backgroundColor: PAL.cyan }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => c.parsed.y.toFixed(1) + '%' } } },
          scales: {
            x: { grid: { display: false }, ticks: { maxRotation: 70, minRotation: 45, font: { size: 9 } } },
            y: { title: { display: true, text: '% of variance' }, grid: { color: GRID() } },
          },
        },
      });
    }

    const strataBody = fillRows('#rq2-strata-table', strata, 6);
    if (strataBody) {
      strataBody.innerHTML = strata
        .map((r) => {
          const tag = r.reorganised
            ? '<span class="verdict verdict-reorg">reorganises</span>'
            : '<span class="verdict verdict-stable">persists</span>';
          return (
            '<tr><td>' + r.label + '</td><td>' + r.hours + '</td><td>' + num(r.ari) + '</td><td>' +
            num(r.null_p05) + '</td><td>' + pct(r.market_mode_share, 0) + '</td><td>' + tag + '</td></tr>'
          );
        })
        .join('');
    }

    const names = Object.fromEntries((rq2.clusters || []).map((c) => [c.cluster, c.name]));
    const stabBody = fillRows('#rq2-stability-table', rq2.zone_stability, 5);
    if (stabBody) {
      stabBody.innerHTML = rq2.zone_stability
        .map((r) => '<tr>' + '<td>' + zCell(r.zone) + '</td><td>' + (names[r.cluster] || r.cluster) + '</td><td>' + pct(r.loyalty, 0) + '</td><td>' + pct(r.defection, 0) + '</td><td>' + num(r.stability) + '</td></tr>')
        .join('');
    }

    const kBody = fillRows('#rq2-k-table', rq2.k_sensitivity, 4);
    if (kBody) {
      kBody.innerHTML = rq2.k_sensitivity
        .map((r) => '<tr' + (r.k === rq2.k ? ' style="font-weight:600"' : '') + '><td>' + r.k + (r.k === rq2.k ? ' (selected)' : '') + '</td><td>' + num(r.silhouette) + '</td><td>' + num(r.mean_ari) + '</td><td>' + num(r.min_ari) + '</td></tr>')
        .join('');
    }
  }

  // --- RQ3 ---
  function renderRq3() {
    const rq3 = CM.rq3 || {};
    answerBox('rq3-answer', 'RQ3', (CM.findings || {}).rq3);

    const stats = document.getElementById('rq3-stats');
    if (stats) {
      stats.innerHTML =
        statCard(num(rq3.auc_levels), 'AUC: correlation → adjacency') +
        statCard(num((rq3.mantel || {}).r), 'Mantel r (price vs hop distance)') +
        statCard(num(rq3.adjacent_mean_r), 'Mean r on direct borders') +
        statCard(num(rq3.distant_mean_r), 'Mean r, no direct border');
    }

    const canvas = document.getElementById('rq3-hops');
    const prof = rq3.hop_profile || [];
    if (canvas && prof.length) {
      if (charts.rq3Hops) charts.rq3Hops.destroy();
      charts.rq3Hops = new Chart(canvas, {
        data: {
          labels: prof.map((r) => r.hops + (r.hops === 1 ? ' hop' : ' hops')),
          datasets: [
            { type: 'line', label: 'r — price levels', data: prof.map((r) => r.r_levels), borderColor: PAL.blue, backgroundColor: PAL.blue, borderWidth: 2, tension: 0.2, yAxisID: 'y' },
            { type: 'line', label: 'r — deseasonalised shocks', data: prof.map((r) => r.r_residual), borderColor: PAL.cyan, backgroundColor: PAL.cyan, borderWidth: 2, borderDash: [5, 4], tension: 0.2, yAxisID: 'y' },
            { type: 'bar', label: 'Share of hours with identical prices', data: prof.map((r) => r.convergence), backgroundColor: MUTED_SOFT(), yAxisID: 'y' },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { position: 'bottom', labels: { boxWidth: 12, padding: 12, font: { size: 11 } } },
            tooltip: {
              mode: 'index',
              intersect: false,
              callbacks: {
                afterBody: (items) => {
                  const row = prof[items[0].dataIndex];
                  return row ? [row.pairs + ' zone pairs', 'mean spread ' + row.mean_spread + ' EUR/MWh'] : [];
                },
              },
            },
          },
          scales: {
            x: { grid: { display: false } },
            y: { min: 0, max: 1, title: { display: true, text: 'Correlation / share of hours' }, grid: { color: GRID() } },
          },
        },
      });
    }

    const explain = document.getElementById('rq3-explain');
    if (explain) {
      const ntc = rq3.ntc_correlation || {};
      explain.innerHTML =
        explainCard(
          'Topology explains most of it',
          'Correlation falls monotonically with every extra hop and adjacency is recovered at AUC ' + num(rq3.auc_levels) + ' — close to but short of perfect. The Mantel test confirms it for the whole matrix at once (r = ' + num((rq3.mantel || {}).r) + ', p = ' + num((rq3.mantel || {}).p_value, 4) + ' over ' + ((rq3.mantel || {}).n_permutations || 0) + ' permutations).'
        ) +
        explainCard(
          'Where it breaks — the wire without the price',
          'Internal Nordic borders and HVDC links carry power but their prices almost never converge: they are congested nearly all the time, so each side keeps its own price. A direct line is necessary but not sufficient for coupling.'
        ) +
        explainCard(
          'Where it breaks — the price without the wire',
          'Zones two or more hops apart inside one coupled bloc move together almost perfectly. Market coupling clears the whole region at once, so prices propagate across intermediate zones without any dedicated line.'
        ) +
        explainCard(
          'Why identical prices mean an uncongested border',
          'Market coupling clears all zones in one welfare-maximising auction, and each zone&rsquo;s price is the shadow price (dual) of its supply-equals-demand constraint. By complementary slackness, the price gap across an interconnector equals the shadow price of that line&rsquo;s capacity limit: <strong>zero while the line has spare capacity, positive only when it binds</strong> (Schweppe et al., 1988). So the share of hours with identical prices measures how often a border is <em>not</em> congested, and the mean spread is the average congestion price per MWh. In flow-based regions such as Core the binding limits sit on internal network elements, so a price gap reflects those constraints weighted by power-flow sensitivities rather than a single border.'
        ) +
        explainCard(
          'Capacity is only part of the story',
          'Across the ' + (ntc.n ?? '—') + ' borders with a genuine per-border NTC, log capacity correlates r = ' + num(ntc.r) + ' with price coupling — a real but moderate link. Bigger borders do couple more, yet what finally separates a coupled border from a congested one is how often the capacity binds and which market-coupling region the two zones sit in.'
        );
    }

    const under = fillRows('#rq3-under-table', rq3.under_coupled, 6);
    if (under) {
      under.innerHTML = rq3.under_coupled
        .map((r) => '<tr><td>' + borderCell(r.a, r.b) + '</td><td>' + num(r.r_levels) + '</td><td>' + num(r.r_residual) + '</td><td>' + pct(r.convergence) + '</td><td>' + num(r.mean_spread, 1) + '</td><td>' + (r.ntc_mw ? Math.round(r.ntc_mw).toLocaleString() + ' MW' : '—') + '</td></tr>')
        .join('');
    }

    const over = fillRows('#rq3-over-table', rq3.over_coupled, 6);
    if (over) {
      over.innerHTML = rq3.over_coupled
        .map((r) => '<tr><td>' + borderCell(r.a, r.b) + '</td><td>' + (r.hops ?? '—') + '</td><td>' + num(r.r_levels) + '</td><td>' + num(r.r_residual) + '</td><td>' + pct(r.convergence) + '</td><td>' + num(r.mean_spread, 1) + '</td></tr>')
        .join('');
    }

    const cong = fillRows('#rq3-congested-table', rq3.congested_borders, 6);
    if (cong) {
      cong.innerHTML = rq3.congested_borders
        .map((r) => '<tr><td>' + borderCell(r.a, r.b) + '</td><td>' + num(r.mean_spread, 1) + ' EUR/MWh</td><td>' + num(r.r_levels) + '</td><td>' + pct(r.convergence) + '</td><td>' + (r.ntc_mw ? Math.round(r.ntc_mw).toLocaleString() + ' MW' : '—') + '</td><td>' + (r.flow_mw ? Math.round(r.flow_mw).toLocaleString() : '—') + '</td></tr>')
        .join('');
    }

    const caveat = document.getElementById('rq3-caveat');
    if (caveat && rq3.data_caveat) {
      const nc = rq3.ntc_coverage || {};
      const fc = rq3.flow_coverage || {};
      caveat.innerHTML =
        '<h3>Data caveat</h3><p>' + rq3.data_caveat +
        ' Usable per-border values: <strong>' + (nc.borders_kept ?? '—') + ' of ' + (nc.borders_raw ?? '—') +
        '</strong> NTC borders, <strong>' + (fc.pairs_validated ?? '—') + ' of ' + (fc.pairs_total ?? '—') +
        '</strong> directed flow pairs.</p>';
    }
  }

  renderRq1();
  renderRq2();
  renderRq3();

  // --- Answers (landing tab) ---
  function renderAnswers() {
    const host = document.getElementById('answers-body');
    if (!host) return;
    const f = CM.findings || {};
    const panel = CM.panel || {};
    const rq1 = CM.rq1 || {};
    const rq2 = CM.rq2 || {};
    const rq3 = CM.rq3 || {};
    if (!f.rq1) {
      host.innerHTML = '<p class="muted">Run: <code>energy-collect analyze-comovement --year 2025</code></p>';
      return;
    }
    const sp = rq1.spectrum || {};
    const va = (rq1.variance || {}).residual || {};
    const lv = (rq1.variance || {}).levels || {};
    const strata = (rq2.seasons || []).concat(rq2.hour_blocks || [], rq2.season_hour || []);
    const reorg = strata.filter((r) => r.reorganised);
    const weakest = strata.reduce((a, b) => (b.market_mode_share < a.market_mode_share ? b : a), strata[0] || {});
    const strongest = strata.reduce((a, b) => (b.market_mode_share > a.market_mode_share ? b : a), strata[0] || {});
    const ks = rq2.k_sensitivity || [];
    const prof = rq3.hop_profile || [];
    const nc = rq3.ntc_coverage || {};
    const fc = rq3.flow_coverage || {};
    const under = (rq3.under_coupled || []).slice(0, 3);
    const over = (rq3.over_coupled || []).slice(0, 3);
    const pairList = (rows) => rows.map((r) => '<span class="nowrap">' + r.a + '–' + r.b + ' (r ' + num(r.r_levels) + ')</span>').join(', ');

    function section(id, question, headline, body, figures, sources) {
      return (
        '<article class="answer-block">' +
        '<h3 class="answer-q"><span class="answer-tag">' + id + '</span>' + question + '</h3>' +
        '<div class="answer-headline">' + headline + '</div>' +
        '<div class="answer-body">' + body + '</div>' +
        '<div class="answer-figures">' +
          figures.map((fg) =>
            '<figure><a href="' + fg.src + '" target="_blank" rel="noopener">' +
            '<img src="' + fg.src + '" alt="' + fg.alt + '" loading="lazy" /></a>' +
            '<figcaption>' + fg.alt + ' — click to open full size</figcaption></figure>'
          ).join('') +
        '</div>' +
        '<details class="answer-sources"><summary>Where these numbers came from</summary><table>' +
        sources.map((r) => '<tr><th>' + r[0] + '</th><td>' + r[1] + '</td></tr>').join('') +
        '</table></details>' +
        '</article>'
      );
    }

    const common =
      'ENTSO-E day-ahead prices (document <strong>A44</strong>), 2025, ' + (panel.n_zones || 43) +
      ' bidding zones. Averaged to hourly UTC because several TSOs moved to a 15-minute market time unit on 1 Oct 2025, ' +
      'then hour-of-day, day-of-week, month-of-year and a 7-day trend removed. ' + (panel.hours || 0).toLocaleString() +
      ' hours are complete for every zone.';

    host.innerHTML =
      section(
        'RQ1',
        'How much of European price co-movement is a single Europe-wide mode, how much is cluster-specific, and how many cluster dimensions are statistically supported?',
        '<strong>One Europe-wide mode carries ' + pct(va.market, 0) + ' of the variance. ' +
          (sp.cluster_dimensions ?? '—') + ' cluster dimensions are statistically supported and carry a further ' +
          pct(va.cluster, 0) + '. The remaining ' + pct(va.noise, 0) + ' is zone-specific noise.</strong>',
        '<p>The Europe-wide mode is a <em>true</em> common factor, not a contrast between two halves of Europe: all ' +
          (sp.zones || 43) + ' of its loadings share the same sign, so it moves every zone in the same direction at once. ' +
          'The ' + (sp.cluster_dimensions ?? '—') + ' cluster dimensions are Nordic, Italian, Iberian, Baltic and an Iberian–Baltic contrast.</p>' +
        '<p>On <em>raw</em> price levels the common mode instead reads ' + pct(lv.market, 0) + '. That extra ' +
          Math.round(100 * (lv.market - va.market)) + ' percentage points is the shared European daily and seasonal ' +
          '<strong>calendar</strong>, not shared market shocks — which is why every number here is computed on deseasonalised prices.</p>',
        [
          { src: 'figures/rq1_modes.png', alt: 'Variance split and eigenvalue spectrum against the surrogate band' },
          { src: 'figures/rq1_loadings.png', alt: 'Eigenvector loadings of the six supported modes' },
        ],
        [
          ['Data', common],
          ['Method', 'Eigen-decomposition of the ' + (sp.zones || 43) + '×' + (sp.zones || 43) + ' Pearson correlation matrix. ' +
            pct(va.market, 0) + ' = λ1/N = ' + num(sp.eigenvalues ? sp.eigenvalues[0] : null) + '/' + (sp.zones || 43) + '.'],
          ['Significance', '<strong>' + (sp.n_surrogates || 0) + ' phase-randomised surrogates</strong> — each keeps a zone’s own power spectrum (so its autocorrelation) and randomises Fourier phases, destroying all cross-zone coupling. A mode counts only if it beats the 95th percentile of its own rank in that null. λ1…λ' +
            (sp.k_significant_95 || 0) + ' do; λ' + ((sp.k_significant_95 || 0) + 1) + ' = ' +
            num(sp.eigenvalues ? sp.eigenvalues[sp.k_significant_95] : null) + ' against a band of ' +
            num(sp.null_q95 ? sp.null_q95[sp.k_significant_95] : null) + ' does not.'],
          ['Cross-check', 'Marchenko–Pastur with an autocorrelation-adjusted sample size. Mean AR(1) = ' + num(sp.mean_ar1) +
            ' means ' + (sp.hours || 0).toLocaleString() + ' hours are worth ≈ <strong>' + num(sp.n_effective, 0) +
            '</strong> independent observations, moving the bound from ' + num(sp.mp_upper_naive ?? 1.15) + ' to <strong>' +
            num(sp.mp_upper_effective) + '</strong>. Also returns ' + (sp.k_significant_mp ?? '—') + ' modes.'],
          ['Code', '<code>eigen_spectrum()</code> in <code>src/energy_collect/comovement.py</code>'],
          ['Output', '<code>data/manifests/comovement_2025.json</code> → <code>rq1</code>'],
        ]
      ) +
      section(
        'RQ2',
        'Do the price clusters persist across seasons and intraday, or does the partition reorganise?',
        '<strong>They persist. The ' + (rq2.k || 8) + ' blocs survive every season and every time of day. The only genuine reorganisation is summer daylight — ' +
          reorg.length + ' of ' + strata.length + ' strata, all of them summer.</strong>',
        '<p>What changes with the clock is not <em>who is in which bloc</em> but <em>how strong the Europe-wide mode is</em>: it runs from <strong>' +
          pct(strongest.market_mode_share, 0) + ' in ' + (strongest.label || '') + '</strong> down to <strong>' +
          pct(weakest.market_mode_share, 0) + ' in ' + (weakest.label || '') +
          '</strong>. The hours with the most solar output are the hours when Europe prices least as one market.</p>' +
        '<p>The blocs are ' + (rq2.clusters || []).map((c) => '<strong>' + c.name + '</strong>').join(', ') +
          '. Iberia and the Baltics never move. The least stable zones are ' +
          (rq2.zone_stability || []).slice(0, 5).map((z) => z.zone).join(', ') +
          ' — every one of them sits on a bloc boundary rather than inside one.</p>',
        [
          { src: 'figures/rq2_persistence.png', alt: 'ARI per stratum against the matched null, and the strength of the common mode' },
          { src: 'figures/rq2_blocs.png', alt: 'The eight price blocs on the map' },
        ],
        [
          ['Data', 'The same deseasonalised hourly price panel as RQ1.'],
          ['Blocs', 'Average-linkage clustering on sqrt(2(1−C)), where C is the correlation <strong>rebuilt from modes 2…' +
            (rq2.n_modes || 6) + ' only</strong>. Dropping mode 1 matters: leaving the Europe-wide mode in makes every zone look similar to every other zone.'],
          ['Choice of k = ' + (rq2.k || 8), esc(rq2.k_selection || '') + '. Silhouette ' + num(rq2.baseline_silhouette) + '.'],
          ['Comparison', '<strong>Adjusted Rand Index</strong> against the full-year partition, for ' +
            (rq2.seasons || []).length + ' seasons, ' + (rq2.hour_blocks || []).length + ' six-hour blocks and ' +
            (rq2.season_hour || []).length + ' season × hour cells.'],
          ['The bar to clear', 'A <strong>permutation null of identical sample size</strong> — random days for a season, random hours-of-day for an hour block, both for a cell, ' +
            (rq2.n_null || 0) + ' replications each. This matters: a quarter of the year gives ARI ≈ ' +
            num((rq2.seasons || [{}])[0].null_median) + ' even when nothing reorganised, so raw ARI alone would be misread. A stratum counts as reorganised only below the null’s 5th percentile.'],
          ['Result', 'ARI ' + num((rq2.summary || {}).min_ari) + '–' + num((rq2.summary || {}).max_ari) + ' across ' +
            strata.length + ' strata. Below the null: ' +
            reorg.map((r) => r.label + ' (' + num(r.ari) + ' vs ' + num(r.null_p05) + ')').join(', ') +
            '. No season or hour block on its own reorganises.'],
          ['Robustness', 'Mean ARI stays ' + num(Math.min(...ks.map((r) => r.mean_ari))) + '–' +
            num(Math.max(...ks.map((r) => r.mean_ari))) + ' for every k from ' + (ks[0] || {}).k + ' to ' +
            (ks[ks.length - 1] || {}).k + ', so the answer does not depend on the cluster count.'],
          ['Code', '<code>stratified_partitions()</code>, <code>adjusted_rand_index()</code>, <code>select_k()</code> in <code>comovement.py</code>'],
          ['Output', '<code>data/manifests/comovement_2025.json</code> → <code>rq2</code>'],
        ]
      ) +
      section(
        'RQ3',
        'Does price co-movement follow the physical interconnection topology, and where does it diverge?',
        '<strong>Yes, closely — but a transmission line turns out to be neither sufficient nor necessary for prices to move together.</strong>',
        '<p>Correlation falls monotonically with every extra hop through the grid, from <strong>' +
          num(prof.length ? prof[0].r_levels : null) + ' at one hop to ' +
          num(prof.length ? prof[prof.length - 1].r_levels : null) + ' at ' +
          (prof.length ? prof[prof.length - 1].hops : '—') + ' hops</strong>. Adjacency is recovered at <strong>AUC ' +
          num(rq3.auc_levels) + '</strong> and the Mantel correlation between price distance and hop distance is <strong>' +
          num((rq3.mantel || {}).r) + '</strong> (p = ' + num((rq3.mantel || {}).p_value, 4) + '). Topology explains most of the picture.</p>' +
        '<p>The exceptions run in both directions and are systematic. <strong>Direct border, weak coupling:</strong> ' +
          pairList(under) + ' — internal Nordic borders where congestion binds essentially all the time (' +
          under[0].a + '–' + under[0].b + ' settles at the same price in only ' + pct(under[0].convergence) +
          ' of hours). <strong>No direct border, strong coupling:</strong> ' + pairList(over) +
          ', all two hops apart — zones inside one coupled bloc, where the market clears the whole region at once.</p>' +
        '<p>Border capacity explains part of it but not most: over the ' + ((rq3.ntc_correlation || {}).n ?? '—') +
          ' borders with a trustworthy per-border capacity figure, log NTC correlates <strong>r = ' +
          num((rq3.ntc_correlation || {}).r) + '</strong> with price coupling.</p>' +
        '<div class="answer-caveat"><strong>One data caveat, stated up front.</strong> ENTSO-E republishes each zone’s <em>aggregate</em> export against every one of its borders. The project’s flow validation already found this for physical flows (A11); the same defect is in the capacity data (A61) — France publishes 2,801 MW identically on BE, DE_LU and IT_NORTH. Those are zone totals, not border figures, and using them would manufacture a result, so they are excluded: <strong>' +
          (nc.borders_kept ?? '—') + ' of ' + (nc.borders_raw ?? '—') + '</strong> NTC borders and <strong>' +
          (fc.pairs_validated ?? '—') + ' of ' + (fc.pairs_total ?? '—') +
          '</strong> directed flow pairs are usable. Every correlation, convergence and spread figure above comes from the <strong>price panel</strong>, which has no such defect. <code>DK_1–DK_2</code> appears as a strongly coupled “non-adjacent” pair, but the Great Belt HVDC link physically connects them — it is simply absent from both the topology config and the ENTSO-E border data. That one is a topology-data gap, not a market finding.</div>',
        [{ src: 'figures/rq3_topology.png', alt: 'Correlation decay by hop distance, and the borders that break the pattern' }],
        [
          ['Co-movement', 'The same 2025 hourly price panel; correlations on raw levels (market integration) with deseasonalised residuals as a cross-check — both decay in the same shape.'],
          ['Topology', 'The border list in <code>config/zones.yaml</code>, restricted to the ' + (panel.n_zones || 43) +
            ' zones in the panel → <strong>' + (rq3.n_adjacent_pairs ?? '—') + ' direct borders</strong>; hop distance by breadth-first search over that graph.'],
          ['Decay profile', 'All ' + (rq3.n_pairs ?? '—') + ' zone pairs grouped by hop distance (' +
            prof.slice(0, 3).map((r) => r.pairs + ' at ' + r.hops).join(', ') + ' hops, …).'],
          ['AUC ' + num(rq3.auc_levels), 'Mann–Whitney U of correlation on the ' + (rq3.n_adjacent_pairs ?? '—') +
            ' direct borders vs the ' + ((rq3.n_pairs || 0) - (rq3.n_adjacent_pairs || 0)) + ' other pairs, p ≈ ' +
            ((rq3.auc_p_value ?? 0).toExponential ? (rq3.auc_p_value).toExponential(0) : rq3.auc_p_value) + '.'],
          ['Mantel r ' + num((rq3.mantel || {}).r), ((rq3.mantel || {}).n_permutations || 0).toLocaleString() +
            ' permutations of the zone labels, comparing the price-distance matrix to the hop-distance matrix.'],
          ['Convergence', 'Share of hours where two zones settle within 0.01 EUR/MWh — the standard sign that a border is <em>not</em> congested. Computed from prices, so it is available for every pair.'],
          ['Theory', 'Zonal prices are the duals of each zone&rsquo;s energy balance in the coupled auction. By complementary slackness the price gap across a border equals the shadow price of its capacity constraint, zero unless the line binds (Schweppe et al., 1988), so convergence share = share of uncongested hours and mean spread = average congestion price. Flow-based regions (Core) generalise this to network-element constraints weighted by PTDFs.'],
          ['Capacity', 'ENTSO-E net transfer capacity (document <strong>A61</strong>), de-duplicated as described above.'],
          ['Code', '<code>topology_comparison()</code> in <code>comovement.py</code>'],
          ['Output', '<code>data/manifests/comovement_2025.json</code> → <code>rq3</code>'],
        ]
      ) +
      '<article class="answer-block answer-together">' +
      '<h3 class="answer-q">The three answers together</h3>' +
      '<ol>' +
      '<li>Europe is <strong>one market plus ' + (sp.cluster_dimensions ?? '—') + ' cluster dimensions</strong>. The common mode is large but far from total, and a quarter of all price variation is purely local.</li>' +
      '<li>Those clusters are <strong>structural, not seasonal</strong>. They hold through winter and summer, night and evening. Only summer daylight breaks them, when solar drives the common mode down to ' + pct(weakest.market_mode_share, 0) + '.</li>' +
      '<li>The clusters <strong>follow the grid, with two systematic exceptions</strong>: congested borders where a line cannot enforce one price, and coupled blocs where the market clears zones together regardless of direct connection.</li>' +
      '</ol>' +
      '<p>The recurring theme across all three: <strong>market-coupling membership, not copper, sets the partition.</strong></p>' +
      '<p class="muted">Reproduce everything: <code>PYTHONPATH=src python3 -m energy_collect.cli analyze-comovement --year 2025</code> then <code>python3 scripts/build_rq_figures.py --year 2025</code>.</p>' +
      '</article>';
  }

  renderAnswers();

  if (G.renderGlossaryPanel && G.PANEL_TERMS) {
    const mapLayerZones = uniqueCodes(
      Object.values(D.map_layers?.layers || {}).flatMap((l) =>
        (l.all || []).flatMap((e) => [e.from, e.to])
      )
    );
    const mapCountryIsos = (D.map?.countries || []).map((c) => c.iso);

    G.renderGlossaryPanel('glossary-map', G.PANEL_TERMS.map, mapLayerZones, Z,
      '<p class="glossary-zones-title">Map country dots (ISO2, static grid only)</p>' +
      '<div class="glossary-zones">' + G.renderZoneGrid(mapCountryIsos, G.COUNTRY_NAMES) + '</div>');

    const priceZones = uniqueCodes(
      Object.keys(D.monthly_prices || {}).concat((D.price_summaries || []).map((r) => r.zone))
    );
    G.renderGlossaryPanel('glossary-prices', G.PANEL_TERMS.prices, priceZones, Z);

    const seasonZones = uniqueCodes(
      Object.keys(D.seasonality?.hourly_profiles || {})
        .concat((D.seasonality?.top_hod_strength || []).map((r) => r.zone))
        .concat((D.load_seasonality?.top_moy_strength || []).map((r) => r.zone))
    );
    G.renderGlossaryPanel('glossary-seasonality', G.PANEL_TERMS.seasonality, seasonZones, Z);

    const teZones = uniqueCodes(
      (D.te_border_edges || D.te_edges || []).flatMap((e) => [e.from, e.to])
    );
    G.renderGlossaryPanel('glossary-te', G.PANEL_TERMS.te, teZones, Z);
    G.renderGlossaryPanel('glossary-shape', G.PANEL_TERMS.shape || [], (D.price_shape || {}).zones || [], Z);

    const mmZones = uniqueCodes(
      (mm.borders || []).flatMap((r) => [r.a, r.b]).concat((nested.zones || []))
    );
    G.renderGlossaryPanel('glossary-mismatch', G.PANEL_TERMS.mismatch || [], mmZones, Z);
    G.renderGlossaryPanel('glossary-regimes', G.PANEL_TERMS.regimes || [], nested.zones || [], Z);
    const netZones = uniqueCodes(
      ((structure.hubs || {}).price || [])
        .concat((structure.hubs || {}).flow || [])
        .concat((structure.hubs || {}).te || [])
        .map((r) => r.zone)
    );
    G.renderGlossaryPanel('glossary-network', G.PANEL_TERMS.network || [], netZones, Z);

    const rq2Zones = uniqueCodes(((CM.rq2 || {}).zone_stability || []).map((r) => r.zone));
    G.renderGlossaryPanel(
      'glossary-answers',
      (G.PANEL_TERMS.rq1 || []).concat(G.PANEL_TERMS.rq2 || [], G.PANEL_TERMS.rq3 || []),
      ((CM.panel || {}).zones || []),
      Z
    );
    G.renderGlossaryPanel('glossary-rq1', G.PANEL_TERMS.rq1 || [], ((CM.panel || {}).zones || []), Z);
    G.renderGlossaryPanel('glossary-rq2', G.PANEL_TERMS.rq2 || [], rq2Zones, Z);
    G.renderGlossaryPanel(
      'glossary-rq3',
      G.PANEL_TERMS.rq3 || [],
      uniqueCodes(((CM.rq3 || {}).under_coupled || []).concat((CM.rq3 || {}).over_coupled || []).flatMap((r) => [r.a, r.b])),
      Z
    );

    const missingZones = uniqueCodes(
      (D.coverage_gaps || []).flatMap((r) => (r.missing || '').split(',').map((s) => s.trim()))
    );
    const allZoneCodes = uniqueCodes(Object.keys(Z).concat(missingZones));
    G.renderGlossaryPanel('glossary-coverage', G.PANEL_TERMS.coverage, allZoneCodes, Z);
  }


  // --- Price shape (after Cäsar, Neumann & Zwickl-Bernhard 2026) ---
  const PS = D.price_shape || {};
  const SERIES = ['#3b82f6', '#f43f5e', '#10b981', '#f59e0b', '#8b5cf6', '#22d3ee', '#ec4899', '#84cc16', '#fb923c', '#14b8a6', '#a78bfa', '#eab308'];
  const shapeMetrics = Object.fromEntries((PS.metrics || []).map((r) => [r.zone, r]));
  const shapeZones = PS.zones || [];
  const blocs = (CM.rq2 || {}).clusters || [];
  const blocOf = {};
  blocs.forEach((c, i) => c.members.forEach((z) => { blocOf[z] = i; }));
  const shapeState = { preset: 'representatives', profile: 'hod', scale: 'relative' };

  function shapePresets() {
    const presets = [];
    const reps = ['DE_LU', 'FR', 'ES', 'IT_NORTH', 'NL', 'NO_4', 'FI', 'EE', 'GR'].filter((z) => shapeZones.includes(z));
    presets.push({ key: 'representatives', label: 'One zone per bloc (overview)', zones: reps });
    const byNeg = (PS.metrics || []).slice().sort((a, b) => b.negative_hours - a.negative_hours).slice(0, 8).map((r) => r.zone);
    presets.push({ key: 'negative', label: 'Most negative hours (top 8)', zones: byNeg });
    blocs.forEach((c, i) => presets.push({ key: 'bloc' + i, label: 'Bloc: ' + c.name, zones: c.members.filter((z) => shapeZones.includes(z)) }));
    return presets;
  }
  const SHAPE_PRESETS = shapePresets();
  const selectedShapeZones = () => (SHAPE_PRESETS.find((p) => p.key === shapeState.preset) || SHAPE_PRESETS[0] || { zones: [] }).zones;

  const presetSelect = document.getElementById('shape-preset');
  if (presetSelect) {
    presetSelect.innerHTML = SHAPE_PRESETS.map((p) => '<option value="' + p.key + '">' + p.label + '</option>').join('');
    presetSelect.addEventListener('change', () => {
      shapeState.preset = presetSelect.value;
      renderShapeProfile();
      renderShapeDuration();
    });
  }
  function bindSegment(attr, key, onChange) {
    const buttons = document.querySelectorAll('.seg-btn[data-' + attr + ']');
    buttons.forEach((btn) => {
      btn.addEventListener('click', () => {
        buttons.forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        shapeState[key] = btn.dataset[attr];
        onChange();
      });
    });
  }
  bindSegment('profile', 'profile', () => renderShapeProfile());
  bindSegment('scale', 'scale', () => renderShapeProfile());

  function renderShapeProfile() {
    const canvas = document.getElementById('shape-profile-chart');
    const prof = (PS.profiles || {})[shapeState.profile];
    if (!canvas || !prof) return;
    const rel = shapeState.scale === 'relative';
    const groups = prof.groups.map((g) => (shapeState.profile === 'hod' ? String(g).padStart(2, '0') + ':00' : g));
    const zones = selectedShapeZones();
    const datasets = zones.map((z, i) => ({
      label: z,
      data: (rel ? prof.relative : prof.absolute)[z],
      borderColor: SERIES[i % SERIES.length],
      backgroundColor: SERIES[i % SERIES.length],
      tension: 0.35,
      pointRadius: 0,
      pointHoverRadius: 4,
    }));
    if (rel) {
      datasets.push({
        label: 'All-zone mean',
        data: prof.europe_relative,
        borderColor: cssVar('--text-3'),
        backgroundColor: cssVar('--text-3'),
        borderDash: [6, 5],
        borderWidth: 1.75,
        tension: 0.35,
        pointRadius: 0,
      });
    }
    if (charts.shapeProfile) charts.shapeProfile.destroy();
    charts.shapeProfile = new Chart(canvas, {
      type: 'line',
      data: { labels: groups, datasets },
      options: {
        ...chartDefaults,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          ...chartDefaults.plugins,
          tooltip: {
            mode: 'index',
            intersect: false,
            callbacks: {
              label: (c) => ' ' + c.dataset.label + ': ' + (rel ? c.parsed.y.toFixed(2) + '× mean' : c.parsed.y.toFixed(1) + ' EUR/MWh'),
            },
          },
        },
        scales: {
          x: { grid: { display: false }, title: { display: true, text: prof.label }, ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 12 } },
          y: {
            title: { display: true, text: rel ? 'Price / zone annual mean' : 'EUR/MWh' },
            grid: { color: GRID() },
          },
        },
      },
    });
  }

  function renderShapeNegative() {
    const canvas = document.getElementById('shape-neg-chart');
    const cum = PS.cumulative_negative || {};
    if (!canvas || !cum.dates) return;
    const finals = Object.entries(cum.series).map(([z, s]) => [z, s[s.length - 1]]).sort((a, b) => b[1] - a[1]);
    const top = finals.slice(0, 8).map((f) => f[0]);
    const muted = cssVar('--chart-muted');
    const datasets = finals
      .filter((f) => !top.includes(f[0]) && f[1] > 0)
      .map(([z]) => ({ label: z, data: cum.series[z], borderColor: muted, borderWidth: 1, pointRadius: 0, inLegend: false, order: 2 }))
      .concat(top.map((z, i) => ({
        label: z + ' · ' + cum.series[z][cum.series[z].length - 1] + ' h',
        data: cum.series[z],
        borderColor: SERIES[i % SERIES.length],
        backgroundColor: SERIES[i % SERIES.length],
        borderWidth: 2.25,
        pointRadius: 0,
        inLegend: true,
        order: 1,
      })));
    const labels = cum.dates;
    if (charts.shapeNeg) charts.shapeNeg.destroy();
    charts.shapeNeg = new Chart(canvas, {
      type: 'line',
      data: { labels, datasets },
      options: {
        ...chartDefaults,
        interaction: { mode: 'nearest', intersect: false, axis: 'x' },
        plugins: {
          ...chartDefaults.plugins,
          legend: { position: 'bottom', labels: { boxWidth: 10, padding: 10, font: { size: 10.5 }, filter: (item, data) => data.datasets[item.datasetIndex].inLegend } },
          tooltip: { mode: 'nearest', intersect: false, callbacks: { title: (items) => items[0].label, label: (c) => ' ' + c.dataset.label.split(' · ')[0] + ': ' + c.parsed.y + ' h' } },
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: {
              autoSkip: false,
              maxRotation: 0,
              callback: (v, i) => (labels[i] && labels[i].endsWith('-01') ? MONTH_NAMES[Number(labels[i].slice(5, 7)) - 1] : null),
            },
          },
          y: { title: { display: true, text: 'Negative-price hours (cumulative)' }, grid: { color: GRID() }, beginAtZero: true },
        },
      },
    });
  }

  function renderShapeDuration() {
    const canvas = document.getElementById('shape-duration-chart');
    const curves = PS.duration_curves || {};
    if (!canvas || !Object.keys(curves).length) return;
    const zones = selectedShapeZones().filter((z) => curves[z]);
    const n = (curves[zones[0]] || []).length;
    const labels = Array.from({ length: n }, (_, i) => Math.round((100 * i) / (n - 1)) + '%');
    const top = Math.max(...zones.map((z) => curves[z][1]));
    const bottom = Math.min(0, ...zones.map((z) => curves[z][n - 2]));
    const datasets = zones.map((z, i) => ({
      label: z,
      data: curves[z],
      borderColor: SERIES[i % SERIES.length],
      backgroundColor: SERIES[i % SERIES.length],
      pointRadius: 0,
      tension: 0.2,
    }));
    if (charts.shapeDuration) charts.shapeDuration.destroy();
    charts.shapeDuration = new Chart(canvas, {
      type: 'line',
      data: { labels, datasets },
      options: {
        ...chartDefaults,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          ...chartDefaults.plugins,
          tooltip: { mode: 'index', intersect: false, callbacks: { title: (items) => 'Share of hours above: ' + items[0].label, label: (c) => ' ' + c.dataset.label + ': ' + c.parsed.y.toFixed(1) + ' EUR/MWh' } },
        },
        scales: {
          x: { grid: { display: false }, title: { display: true, text: 'Share of the year (hours sorted from highest price)' }, ticks: { maxTicksLimit: 6, maxRotation: 0 } },
          y: { title: { display: true, text: 'EUR/MWh' }, grid: { color: GRID() }, max: Math.ceil(top / 50) * 50, min: Math.floor(bottom / 25) * 25 },
        },
      },
    });
  }

  function renderShapeAlignment() {
    const canvas = document.getElementById('shape-align-chart');
    if (!canvas || !PS.metrics) return;
    const groups = blocs.map((c, i) => ({ name: c.name, color: SERIES[i % SERIES.length], points: [] }));
    const other = { name: 'Other', color: PAL.slate, points: [] };
    PS.metrics.forEach((r) => {
      if (r.rho_hod == null || r.amp_hod == null) return;
      const g = blocOf[r.zone] != null ? groups[blocOf[r.zone]] : other;
      g.points.push({ x: r.rho_hod, y: r.amp_hod, zone: r.zone });
    });
    const datasets = groups.concat(other.points.length ? [other] : []).map((g) => ({
      label: g.name,
      data: g.points,
      backgroundColor: alpha(g.color, 0.85),
      borderColor: g.color,
      pointRadius: 6,
      pointHoverRadius: 9,
    }));
    if (charts.shapeAlign) charts.shapeAlign.destroy();
    charts.shapeAlign = new Chart(canvas, {
      type: 'scatter',
      data: { datasets },
      options: {
        ...chartDefaults,
        plugins: {
          ...chartDefaults.plugins,
          tooltip: { callbacks: { label: (c) => ' ' + c.raw.zone + ' (' + c.dataset.label + '): ρ ' + c.raw.x.toFixed(2) + ', amplitude ' + c.raw.y.toFixed(2) + '×' } },
        },
        scales: {
          x: { title: { display: true, text: 'Alignment ρ with the all-zone daily profile' }, grid: { color: GRID() }, max: 1 },
          y: { title: { display: true, text: 'Amplitude ratio (zone range / all-zone range)' }, grid: { color: GRID() } },
        },
      },
    });
  }

  function renderShapeCharts() {
    renderShapeProfile();
    renderShapeNegative();
    renderShapeDuration();
    renderShapeAlignment();
  }

  // Static parts of the panel: headline numbers, findings and the sortable table.
  (function renderShapeStatic() {
    const sum = PS.summary || {};
    const stats = document.getElementById('shape-stats');
    if (stats && sum.n_zones) {
      stats.innerHTML =
        statCard(sum.zones_with_negative + ' / ' + sum.n_zones, 'Zones with negative prices in ' + (PS.year || D.year)) +
        statCard(String((sum.most_negative || {}).hours ?? '—'), 'Negative hours in ' + ((sum.most_negative || {}).zone || '—') + ', the most of any zone') +
        statCard(String((sum.zones_floor_at_zero || []).length), 'Zones that never clear below 0 EUR/MWh') +
        statCard(num(sum.hod_shape_similarity_mean), 'Mean similarity of daily shapes (r)');
    }
    const findings = PS.findings || {};
    const fEl = document.getElementById('shape-findings');
    if (fEl) {
      fEl.innerHTML =
        explainCard('Negative prices follow market rules too', esc(findings.negatives)) +
        explainCard('Not a simple solar story', esc(findings.solar)) +
        explainCard('One European daily rhythm, with exceptions', esc(findings.shape)) +
        explainCard(
          'Why these metrics',
          'Cäsar, Neumann &amp; Zwickl-Bernhard (2026) show that energy-system models get the price <em>level</em> right but compress its <em>shape</em>: too flat a day, no negative hours, no spikes. Their alignment and compression measures turn that into numbers. Applied across zones they show how differently the same European market behaves from place to place.'
        );
    }
    const body = document.querySelector('#shape-table tbody');
    if (!body || !PS.metrics) return;
    const fmt = {
      zone: (r) => '<span class="zone-code" title="' + esc(zLabel(r.zone)) + '">' + r.zone + '</span>',
      mean: (r) => num(r.mean, 1),
      negative_hours: (r) => r.negative_hours + ' <small>(' + pct(r.negative_share) + ')</small>',
      near_zero_share: (r) => pct(r.near_zero_share),
      spike_share: (r) => pct(r.spike_share),
      peak: (r) => num(r.peak, 0),
      lowest: (r) => num(r.lowest, 0),
      daily_spread: (r) => num(r.daily_spread, 1),
      rho_hod: (r) => num(r.rho_hod),
      amp_hod: (r) => num(r.amp_hod) + '×',
      solar_share: (r) => (r.solar_share == null ? '—' : num(r.solar_share, 1) + '%'),
      wind_share: (r) => (r.wind_share == null ? '—' : num(r.wind_share, 1) + '%'),
    };
    const keys = Object.keys(fmt);
    let sortKey = 'negative_hours';
    let sortDir = -1;
    function draw() {
      const rows = PS.metrics.slice().sort((a, b) => {
        const va = a[sortKey];
        const vb = b[sortKey];
        if (va == null) return 1;
        if (vb == null) return -1;
        return (va > vb ? 1 : va < vb ? -1 : 0) * sortDir;
      });
      body.innerHTML = rows
        .map((r) => '<tr>' + keys.map((k) => '<td' + (k === 'zone' ? '' : ' class="num"') + '>' + fmt[k](r) + '</td>').join('') + '</tr>')
        .join('');
      document.querySelectorAll('#shape-table th[data-key]').forEach((th) => {
        th.setAttribute('aria-sort', th.dataset.key === sortKey ? (sortDir > 0 ? 'ascending' : 'descending') : 'none');
      });
    }
    document.querySelectorAll('#shape-table th[data-key]').forEach((th) => {
      th.tabIndex = 0;
      const activate = () => {
        if (sortKey === th.dataset.key) sortDir = -sortDir;
        else {
          sortKey = th.dataset.key;
          sortDir = sortKey === 'zone' ? 1 : -1;
        }
        draw();
      };
      th.addEventListener('click', activate);
      th.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter' || ev.key === ' ') {
          ev.preventDefault();
          activate();
        }
      });
    });
    draw();
  })();

  // --- Theme switching: recolour the basemap, the map edges and every chart ---
  document.addEventListener('dashboard:themechange', () => {
    applyChartTheme();
    chartDefaults = buildChartDefaults();
    baseTiles.setUrl(tileUrl());
    renderMapEdges();
    Object.keys(charts).forEach((k) => {
      if (charts[k]) {
        charts[k].destroy();
        charts[k] = null;
      }
    });
    renderRq1();
    renderRq2();
    renderRq3();
    const active = document.querySelector('.tab.active');
    if (active) renderTab(active.dataset.tab);
  });

  if (S.renderSourcesPanel) {
    S.renderSourcesPanel('sources-prices', 'prices', D);
    S.renderSourcesPanel('sources-seasonality', 'seasonality', D);
    S.renderSourcesPanel('sources-te', 'te', D);
    S.renderSourcesPanel('sources-shape', 'shape', D);
    S.renderSourcesPanel('sources-mismatch', 'mismatch', D);
    S.renderSourcesPanel('sources-regimes', 'regimes', D);
    S.renderSourcesPanel('sources-network', 'network', D);
    S.renderSourcesPanel('sources-coverage', 'coverage', D);
  }
})();
