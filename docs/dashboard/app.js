(function () {
  const D = window.DASHBOARD_DATA;
  if (!D) {
    document.body.innerHTML =
      '<p style="padding:2rem;font-family:system-ui">Run: <code>PYTHONPATH=src python3 -m energy_collect.cli build-dashboard --year 2025</code></p>';
    return;
  }

  const charts = { price: null, hod: null, quarter: null, monthSeason: null, nestedTe: null, substations: null, gemType: null };
  const G = window.DASHBOARD_GLOSSARY || {};
  const S = window.DASHBOARD_SOURCES || {};
  const Z = D.zone_names || {};
  const zLabel = (code) => (G.zoneLabel ? G.zoneLabel(code, Z) : code);
  const zCell = (code) =>
    '<div class="zone-cell">' + (G.formatZoneCell ? G.formatZoneCell(code, Z) : '<span class="zone-code">' + code + '</span>') + '</div>';
  const zChartLabel = (code) => code + ' — ' + zLabel(code);

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

  const chartDefaults = {
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
        grid: { color: '#eef2f6' },
        ticks: { font: { size: 11 } },
      },
    },
  };

  document.getElementById('subtitle').textContent =
    `ENTSO-E ${D.year} · ${D.zones_with_prices || '—'} zones with prices · updated ${new Date(D.generated_at).toLocaleDateString()}`;

  // --- Tabs (lazy chart render) ---
  document.querySelectorAll('.tab').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach((b) => b.classList.remove('active'));
      document.querySelectorAll('.panel').forEach((p) => p.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById('panel-' + btn.dataset.tab).classList.add('active');

      const tab = btn.dataset.tab;
      if (tab === 'map') {
        map.invalidateSize();
        renderMapEdges();
      }
      if (tab === 'prices') renderPriceChart();
      if (tab === 'seasonality') renderSeasonalityCharts();
      if (tab === 'regimes') renderNestedTeChart();
      if (tab === 'network') renderNetworkCharts();
    });
  });

  // --- Map ---
  const MAP_PALETTES = {
    flow: { weak: [219, 234, 254], strong: [30, 64, 175], label: 'Mean flow (MW)', unit: 'MW' },
    price: { weak: [254, 243, 199], strong: [194, 65, 12], label: 'Price correlation (r)', unit: 'r' },
    te: { weak: [237, 233, 254], strong: [109, 40, 217], label: 'Transfer entropy', unit: 'bits' },
  };

  function hexRgb(r, g, b) {
    return '#' + [r, g, b].map((v) => Math.round(v).toString(16).padStart(2, '0')).join('');
  }

  function gradientColor(kind, norm) {
    const p = MAP_PALETTES[kind] || MAP_PALETTES.flow;
    const t = Math.max(0, Math.min(1, norm));
    const r = p.weak[0] + (p.strong[0] - p.weak[0]) * t;
    const g = p.weak[1] + (p.strong[1] - p.weak[1]) * t;
    const b = p.weak[2] + (p.strong[2] - p.weak[2]) * t;
    return hexRgb(r, g, b);
  }

  function gradientCss(kind) {
    const p = MAP_PALETTES[kind] || MAP_PALETTES.flow;
    return `linear-gradient(90deg, ${hexRgb(...p.weak)}, ${hexRgb(...p.strong)})`;
  }

  const map = L.map('map').setView([54, 15], 4);
  L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
    maxZoom: 18,
    attribution: '&copy; OpenStreetMap & CARTO',
  }).addTo(map);

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
    const palette = MAP_PALETTES[mapEdgeKind];

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
        radius: 5,
        color: '#1e3a5f',
        fillColor: '#64748b',
        fillOpacity: 0.55,
        weight: 1,
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
    const colors = ['#2563a8', '#dc2626', '#16a34a', '#9333ea', '#ea580c'];

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
          backgroundColor: '#2563a8aa',
          borderColor: '#2563a8',
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
          borderColor: '#ea580c',
          backgroundColor: '#ea580c22',
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
          borderColor: '#2563a8',
          backgroundColor: '#2563a822',
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

  function renderReversalTable() {
    const sel = document.getElementById('regime-select');
    const key = sel ? sel.value : 'hod';
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
    regimeSelect.addEventListener('change', renderReversalTable);
    renderReversalTable();
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
    const scale = (nested.scale_table || []).slice(0, 8);
    const labels = scale.map((r) => r.a + '–' + r.b);
    const yearData = scale.map((r) => r.year_a_to_b);
    const monthData = scale.map((r) => r.month_avg_a_to_b);
    const weekData = scale.map((r) => r.week_avg_a_to_b);
    const hodData = scale.map((r) => r.hod_avg_a_to_b);
    const datasets = [
      { label: 'Year TE A→B', data: yearData, backgroundColor: '#2563a8aa' },
      { label: 'Month-average A→B', data: monthData, backgroundColor: '#ea580caa' },
      { label: 'Week-average A→B', data: weekData, backgroundColor: '#16a34aaa' },
      { label: 'HOD-average A→B', data: hodData, backgroundColor: '#9333eaaa' },
    ];
    if (charts.nestedTe) {
      charts.nestedTe.data.labels = labels;
      charts.nestedTe.data.datasets = datasets;
      charts.nestedTe.update();
      charts.nestedTe.resize();
      return;
    }
    charts.nestedTe = new Chart(canvas, {
      type: 'bar',
      data: { labels, datasets },
      options: {
        ...chartDefaults,
        plugins: {
          ...chartDefaults.plugins,
          title: {
            display: true,
            text: 'Nested TE (A→B) vs averaging — top pairs in corridor set',
            font: { size: 12, weight: '600' },
          },
        },
        scales: {
          ...chartDefaults.scales,
          y: { ...chartDefaults.scales.y, title: { display: true, text: 'TE (bits)', font: { size: 11 } } },
        },
      },
    });
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
          data: { labels, datasets: [{ label: 'Substations', data, backgroundColor: '#2563a8aa' }] },
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
          data: { labels, datasets: [{ label: 'MW', data, backgroundColor: '#16a34aaa' }] },
          options: {
            ...chartDefaults,
            indexAxis: 'y',
            plugins: { ...chartDefaults.plugins, legend: { display: false } },
            scales: {
              x: { title: { display: true, text: 'MW', font: { size: 11 } }, grid: { color: '#eef2f6' } },
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

    const missingZones = uniqueCodes(
      (D.coverage_gaps || []).flatMap((r) => (r.missing || '').split(',').map((s) => s.trim()))
    );
    const allZoneCodes = uniqueCodes(Object.keys(Z).concat(missingZones));
    G.renderGlossaryPanel('glossary-coverage', G.PANEL_TERMS.coverage, allZoneCodes, Z);
  }

  if (S.renderSourcesPanel) {
    S.renderSourcesPanel('sources-prices', 'prices', D);
    S.renderSourcesPanel('sources-seasonality', 'seasonality', D);
    S.renderSourcesPanel('sources-te', 'te', D);
    S.renderSourcesPanel('sources-mismatch', 'mismatch', D);
    S.renderSourcesPanel('sources-regimes', 'regimes', D);
    S.renderSourcesPanel('sources-network', 'network', D);
    S.renderSourcesPanel('sources-coverage', 'coverage', D);
  }
})();
