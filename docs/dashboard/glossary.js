/** Term definitions and zone/country labels for dashboard glossaries. */
(function (global) {
  const COUNTRY_NAMES = {
    AL: 'Albania',
    AT: 'Austria',
    BA: 'Bosnia and Herzegovina',
    BE: 'Belgium',
    BG: 'Bulgaria',
    CH: 'Switzerland',
    CZ: 'Czech Republic',
    DE: 'Germany',
    DK: 'Denmark',
    EE: 'Estonia',
    ES: 'Spain',
    FI: 'Finland',
    FR: 'France',
    GB: 'Great Britain',
    GR: 'Greece',
    HR: 'Croatia',
    HU: 'Hungary',
    IE: 'Ireland',
    IT: 'Italy',
    LT: 'Lithuania',
    LU: 'Luxembourg',
    LV: 'Latvia',
    MD: 'Moldova',
    ME: 'Montenegro',
    MK: 'North Macedonia',
    NL: 'Netherlands',
    NO: 'Norway',
    PL: 'Poland',
    PT: 'Portugal',
    RO: 'Romania',
    RS: 'Serbia',
    SE: 'Sweden',
    SI: 'Slovenia',
    SK: 'Slovakia',
    UA: 'Ukraine',
    XK: 'Kosovo',
  };

  const TE_PARAMS_EXPLAIN =
    '<details class="te-params">' +
    '<summary>What the parameters mean (k, α, r, l, …)</summary>' +
    '<div class="te-params-body">' +
    '<ul class="te-params-list">' +
    '<li><strong>k = 4 (k-NN)</strong> — <em>k-nearest neighbours</em>: how many similar past hourly price patterns are used to estimate local density (Leonenko estimator). Larger k = smoother, more global estimate.</li>' +
    '<li><strong>α = 1 (alpha)</strong> — <em>Rényi order</em>. α = 1 is the Shannon case (standard entropy/TE). α &lt; 1 would weight rare price spikes more heavily; we use α = 1 here.</li>' +
    '<li><strong>r = 1</strong> — <em>target memory</em> (hours): how much of the <strong>target</strong> zone’s own past is included when predicting its next price. r = 1 → previous hour only (<code>x<sub>t−1</sub></code>).</li>' +
    '<li><strong>l = 1</strong> — <em>source memory</em> (hours): how much of the <strong>source</strong> zone’s past is added. l = 1 → source’s previous hour (<code>y<sub>t−1</sub></code>). Edge A → B asks: does A’s past help forecast B’s next hour beyond B’s own past?</li>' +
    '<li><strong>Effective (shuffle-corrected)</strong> — <em>ERTE</em>: subtract TE measured on a time-shuffled source series to remove finite-sample false positives.</li>' +
    '<li><strong>bits</strong> — information in log base 2; higher = more predictable directed coupling.</li>' +
    '<li><strong>Deseasonalised input</strong> — daily / weekly / yearly mean price patterns removed first so TE is not driven by shared clocks and seasons.</li>' +
    '</ul>' +
    '<p class="te-params-note"><em>Note:</em> TE memory <strong>r</strong> and <strong>l</strong> are lags in hours — not Pearson <strong>r</strong> on the price-coupling map layer.</p>' +
    '</div></details>';

  const MAP_STRENGTH_EXPLAIN = {
    flow: {
      title: 'Physical flow strength',
      body:
        '<p><strong>Raw strength</strong> = mean <em>absolute</em> hourly cross-border flow in <strong>MW</strong> over 2025 (ENTSO-E document A11), after validation. ' +
        'One directed edge per border (exporter → importer). Uses typical flow magnitude, not net signed direction.</p>' +
        '<p>Tooltip shows MW. Every validated border flow is shown in both toggle modes.</p>',
    },
    price: {
      title: 'Price coupling strength',
      body:
        '<p><strong>Raw strength</strong> = Pearson correlation <strong>r</strong> between hourly day-ahead prices (2025). ' +
        '<strong>All connections</strong> draws every zone pair with data. ' +
        '<strong>Strongest only</strong> keeps pairs with <strong>|r| ≥ 0.80</strong> (slightly below the 0.85 graph threshold so the gradient is visible; dashed = below 0.85). Edges are undirected (↔).</p>' +
        '<p>Ranking and color use <strong>|r|</strong> across whichever set is visible. Tooltip shows signed r.</p>',
    },
    te: {
      title: 'Transfer entropy strength',
      body:
        '<p><strong>Raw strength</strong> = effective <strong>k-NN Rényi TE</strong> in <strong>bits</strong>, shuffle-corrected, on <strong>deseasonalised</strong> hourly ENTSO-E prices.</p>' +
        TE_PARAMS_EXPLAIN +
        '<p><strong>All connections</strong> = all <strong>177</strong> config border directions (TE = 0 when not estimated). ' +
        '<strong>Strongest only</strong> = cross-border pairs with TE ≥ minimum threshold. Gradient is re-scaled per toggle. Edges are directed (→).</p>',
    },
    common:
      '<p class="strength-explain-note"><strong>Gradient color &amp; line width</strong> use min–max normalization over the visible edge set (pale = weakest shown, dark = strongest shown). ' +
      'Sub-threshold pairs appear only in <em>All connections</em>.</p>',
  };

  const PAGE_STRENGTH_EXPLAIN = {
    prices:
      '<div class="strength-explain strength-explain-price">' +
      '<h3>How price coupling strength is defined</h3>' +
      '<p>On the <strong>Map</strong> tab, the price layer connects zones whose hourly day-ahead prices are strongly correlated over 2025. ' +
      '<strong>Strength = Pearson r</strong> between the two zones’ hourly price series. Only pairs with <strong>|r| ≥ 0.85</strong> appear.</p>' +
      '<p>High correlation here means when wholesale prices rise or fall in one zone, a neighbour tends to move the same way — a sign of market coupling, not necessarily a physical cable. ' +
      'Line color on the map ranks <strong>|r|</strong> within that layer (pale = weaker coupling among shown pairs, dark = strongest).</p>' +
      '</div>',
    te:
      '<div class="strength-explain strength-explain-te">' +
      '<h3>How TE strength is defined</h3>' +
      '<p><strong>Strength = transfer entropy in bits</strong> — directed information flow from source zone to target zone. ' +
      'Higher TE means knowing the source’s past prices helps predict the target’s <em>next</em> hour beyond the target’s own history.</p>' +
      '<p>Method: k-NN Rényi TE (Tabachová et al. 2026) with shuffle bias correction (effective RTE).</p>' +
      TE_PARAMS_EXPLAIN +
      '<p>Map layer: <strong>cross-border neighbours</strong> from <code>config/zones.yaml</code>. ' +
      '“All” shows every border direction; “Strongest” keeps TE ≥ minimum. Table below lists top border pairs.</p>' +
      '</div>',
  };

  const PANEL_TERMS = {
    map: [
      ['ENTSO-E', 'European Network of Transmission System Operators for Electricity — publishes transparency data via API.'],
      ['TSO', 'Transmission System Operator — company that runs the high-voltage grid in a country or region.'],
      ['Bidding zone', 'Smallest market area for day-ahead pricing (may split a country, e.g. Italy has six zones).'],
      ['MW', 'Megawatt — rate of power flow, load, or generation (1 MW = 1 million watts).'],
      ['Pearson r', 'Correlation coefficient (−1 to +1). Price layer: strength = r on hourly DA prices; only |r| ≥ 0.85 shown.'],
      ['Strength (flow)', 'Mean absolute hourly border flow in MW (2025 ENTSO-E flows, validated directed edge).'],
      ['Strength (TE)', 'Effective k-NN Rényi TE in bits on deseasonalised prices; cross-border neighbours on map.'],
      ['Gradient color', 'Pale = weakest, dark = strongest within the selected layer (min–max of raw strength). Line width scales too.'],
      ['Strongest only', 'Price: |r| ≥ 0.80 (gradient band; dashed below 0.85). TE: TE ≥ minimum on border pairs. Flow: all validated borders.'],
      ['All connections', 'Every computed pair for that layer, including below-threshold price r and TE (still gradient-colored).'],
      ['OSM', 'OpenStreetMap — underlying grid geometry in PyPSA-Eur static layer (substation lat/lon).'],
      ['PyPSA-Eur', 'Open European grid model (Zenodo) — transmission lines & substations; zone coordinates on map.'],
      ['GEM', 'Global Energy Monitor GIPT — power-plant capacity by country; merged on graph nodes (reference only).'],
      ['zones.yaml', 'Project config — 45 zone codes, EIC IDs, border neighbours (structural / TE borders).'],
      ['DE_LU', 'Combined Germany + Luxembourg bidding zone (use this code, not DE alone, for ENTSO-E prices).'],
      ['IE_SEM', 'Ireland Single Electricity Market — all-island wholesale market (Republic + Northern Ireland).'],
    ],
    prices: [
      ['DA / Day-ahead', 'Wholesale market where prices for tomorrow\'s delivery are set today (ENTSO-E document A44).'],
      ['EUR/MWh', 'Euros per megawatt-hour — standard unit for electricity price (energy, not power).'],
      ['ENTSO-E', 'European transparency platform; our prices come from document type A44.'],
      ['Zone', 'ENTSO-E bidding zone code — may differ from country ISO (e.g. DE_LU, IT_NORTH, SE_3).'],
      ['Price coupling (r)', 'Pearson correlation of hourly DA prices between two zones; map layer uses pairs with |r| ≥ 0.85.'],
      ['Map price layer', 'Same r metric as above; color ranks |r| among included pairs (see Map tab).'],
    ],
    seasonality: [
      ['HOD', 'Hour-of-day — average price pattern repeating every 24 hours (night vs peak).'],
      ['DOW', 'Day-of-week — weekday vs weekend average offset, removed after HOD.'],
      ['MOY', 'Month-of-year — seasonal level shift (winter vs summer), captures quarterly effects.'],
      ['UTC', 'Coordinated Universal Time — all hourly timestamps are in UTC.'],
      ['Q1–Q4', 'Calendar quarters: Q1 Jan–Mar, Q2 Apr–Jun, Q3 Jul–Sep, Q4 Oct–Dec.'],
      ['σ (residual)', 'Standard deviation of the deseasonalised series — spread after removing predictable patterns.'],
      ['MW', 'Megawatt — unit for electricity load (consumption rate).'],
      ['Residual', 'Price (or load) left after removing HOD, DOW, MOY and trend — input to transfer entropy.'],
    ],
    te: [
      ['TE', 'Transfer entropy — bits of directed information flow: does source A\'s past help predict target B\'s future?'],
      ['RTE', 'Rényi transfer entropy — generalisation of TE with order parameter α (tail vs bulk sensitivity).'],
      ['ERTE', 'Effective RTE — TE minus shuffle bias (source time order destroyed) for finite-sample correction.'],
      ['k (k-NN)', 'Number of nearest neighbours (k = 4) used to estimate local density of price patterns — Leonenko k-NN estimator.'],
      ['α (alpha)', 'Rényi entropy order; α = 1 → Shannon TE. α < 1 would emphasise tail / spike events.'],
      ['r (memory)', 'Target-zone history length in hours (r = 1 → previous hour of target prices). Not Pearson r.'],
      ['l (memory)', 'Source-zone history length in hours (l = 1 → previous hour of source prices).'],
      ['Effective / ERTE', 'Apparent TE minus mean TE on time-shuffled source — reduces spurious coupling.'],
      ['bits', 'Information unit (log₂). Map/table strength = effective TE in bits.'],
      ['Source → Target', 'Directed edge: information flows from source zone past to target zone future.'],
      ['Deseasonalised', 'Daily/weekly/yearly mean patterns removed so TE is not driven by shared daily cycles.'],
      ['TE strength (bits)', 'Raw edge weight on map and in tables; higher = stronger directed price information flow.'],
      ['Map TE layer', 'Cross-border neighbour pairs only; color = normalized TE among those edges.'],
    ],
    mismatch: [
      ['Congested trade', 'High mean |physical flow| but weak Pearson price correlation (FR–ES type).'],
      ['Paper coupling', 'Strong price correlation with little physical exchange on that border.'],
      ['Aligned strong', 'Both large physical flow and high price correlation.'],
      ['Mean |MW|', 'Average absolute hourly ENTSO-E A11 flow on the canonical border.'],
      ['Pearson r', 'Hourly day-ahead price correlation between the two zones (A44).'],
      ['TE max', 'Larger of the two directed TE values on the pair (k-NN if computed, else discrete).'],
    ],
    regimes: [
      ['Reversal', 'The zone that leads on TE (higher directed TE) changes across HOD, DOW, season, or month bins.'],
      ['HOD TE', 'TE using only hours of that clock hour; lag-1 is yesterday at the same hour.'],
      ['Nested TE', 'Year TE compared with the average of month, week, and hour-of-day TE on the same pair.'],
      ['Discrete TE', 'Binned Schreiber transfer entropy used for regime/nested runs (faster than k-NN).'],
      ['DJF / JJA', 'Meteorological winter / summer (Dec–Feb / Jun–Aug).'],
    ],
    network: [
      ['Hub strength', 'Sum of absolute edge weights touching a zone (r, MW, or TE bits depending on layer).'],
      ['Degree', 'Number of edges incident to the zone on that layer.'],
      ['Price community', 'Connected component of the |r| ≥ 0.85 price-coupling graph.'],
      ['OSM lines', 'PyPSA-Eur transmission lines from OpenStreetMap (voltage, geometry).'],
      ['GEM GIPT', 'Global Energy Monitor plant units; operating capacity aggregated by country and type.'],
    ],
    coverage: [
      ['ENTSO-E', 'European Network of Transmission System Operators — Transparency Platform API.'],
      ['A44 / DA prices', 'Document 12.1.D — day-ahead market clearing price (EUR/MWh).'],
      ['A65 / Load', 'Document 6.1.A — total actual consumption in the zone (MW).'],
      ['A75 / Generation', 'Document 16.1.B&C — actual generation by fuel type / PSR (MW).'],
      ['A85 / Imbalance', 'Document 17.1.G — balancing energy price (not all TSOs publish).'],
      ['A11 / Flows', 'Document 12.1.G — physical cross-border power flow (MW).'],
      ['PSR', 'Production type — fuel/category breakdown in generation data.'],
      ['Full year', 'All 12 months returned data for that zone; missing = API returned empty series.'],
    ],
  };

  function zoneCountry(iso) {
    return COUNTRY_NAMES[iso] || iso;
  }

  function zoneLabel(code, zoneNames) {
    const names = zoneNames || {};
    if (names[code]) return names[code];
    if (COUNTRY_NAMES[code]) return COUNTRY_NAMES[code];
    const prefix = code.split('_')[0];
    if (COUNTRY_NAMES[prefix]) return COUNTRY_NAMES[prefix] + ' (' + code + ')';
    return code;
  }

  function formatZoneCell(code, zoneNames) {
    const name = zoneLabel(code, zoneNames);
    if (name === code) {
      return '<span class="zone-code">' + code + '</span>';
    }
    return (
      '<span class="zone-code" title="' + name + '">' + code + '</span>' +
      '<span class="zone-name">' + name + '</span>'
    );
  }

  function renderTermList(terms) {
    return terms
      .map(function (t) {
        return '<div class="glossary-term"><dt>' + t[0] + '</dt><dd>' + t[1] + '</dd></div>';
      })
      .join('');
  }

  function renderZoneGrid(codes, zoneNames) {
    const sorted = codes.slice().sort();
    return sorted
      .map(function (code) {
        const name = zoneLabel(code, zoneNames);
        return (
          '<div class="glossary-zone">' +
          '<code>' + code + '</code>' +
          '<span>' + name + '</span>' +
          '</div>'
        );
      })
      .join('');
  }

  function renderGlossaryPanel(containerId, terms, zoneCodes, zoneNames, extraHtml) {
    const el = document.getElementById(containerId);
    if (!el) return;
    let html =
      '<details class="glossary" open>' +
      '<summary>Terms &amp; codes on this page</summary>' +
      '<div class="glossary-terms">' + renderTermList(terms) + '</div>';
    if (zoneCodes && zoneCodes.length) {
      html +=
        '<p class="glossary-zones-title">Bidding zones &amp; countries referenced</p>' +
        '<div class="glossary-zones">' + renderZoneGrid(zoneCodes, zoneNames) + '</div>';
    }
    if (extraHtml) html += extraHtml;
    html += '</details>';
    el.innerHTML = html;
  }

  function renderMapStrengthExplain(kind) {
    const block = MAP_STRENGTH_EXPLAIN[kind] || MAP_STRENGTH_EXPLAIN.flow;
    return (
      '<div class="strength-explain strength-explain-' + kind + '">' +
      '<h3>' + block.title + '</h3>' +
      block.body +
      MAP_STRENGTH_EXPLAIN.common +
      '</div>'
    );
  }

  global.DASHBOARD_GLOSSARY = {
    COUNTRY_NAMES,
    TE_PARAMS_EXPLAIN,
    MAP_STRENGTH_EXPLAIN,
    PAGE_STRENGTH_EXPLAIN,
    renderMapStrengthExplain,
    PANEL_TERMS,
    zoneLabel,
    zoneCountry,
    formatZoneCell,
    renderGlossaryPanel,
    renderZoneGrid,
  };
})(window);
