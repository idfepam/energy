/** Page chrome: theme, navigation drawer, deep links, hero network, count-ups and reveals. */
(function () {
  const root = document.documentElement;
  const body = document.body;
  const D = window.DASHBOARD_DATA || {};
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const tabs = Array.from(document.querySelectorAll('.tab'));
  const tabIds = tabs.map((t) => t.dataset.tab);
  const cssVar = (name) => getComputedStyle(root).getPropertyValue(name).trim();

  // --- Theme ---
  const themeBtn = document.getElementById('theme-btn');
  function setThemeColorMeta() {
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', cssVar('--bg'));
  }
  setThemeColorMeta();
  if (themeBtn) {
    themeBtn.addEventListener('click', () => {
      const next = root.dataset.theme === 'light' ? 'dark' : 'light';
      root.dataset.theme = next;
      try {
        localStorage.setItem('dashboard-theme', next);
      } catch (e) {
        /* storage may be unavailable; the theme still applies for this visit */
      }
      setThemeColorMeta();
      document.dispatchEvent(new CustomEvent('dashboard:themechange', { detail: { theme: next } }));
      hero.refreshColors();
    });
  }

  // --- Navigation drawer (phones and small tablets) ---
  const menuBtn = document.getElementById('menu-btn');
  const scrim = document.getElementById('scrim');
  function setNav(open) {
    body.classList.toggle('nav-open', open);
    if (menuBtn) menuBtn.setAttribute('aria-expanded', String(open));
    if (scrim) scrim.hidden = !open;
  }
  if (menuBtn) menuBtn.addEventListener('click', () => setNav(!body.classList.contains('nav-open')));
  if (scrim) scrim.addEventListener('click', () => setNav(false));
  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape') setNav(false);
  });

  // --- Tabs: deep links, title, entrance animation, scroll reset ---
  const current = document.getElementById('topbar-current');
  function onTabShown(btn, opts) {
    tabs.forEach((t) => t.removeAttribute('aria-current'));
    btn.setAttribute('aria-current', 'page');
    if (current) current.textContent = btn.textContent.trim();
    document.title = btn.dataset.tab === 'answers'
      ? 'European Energy Dependency Map'
      : btn.textContent.trim() + ' · European Energy Dependency Map';
    const panel = document.getElementById('panel-' + btn.dataset.tab);
    if (panel && !reduceMotion) {
      panel.classList.remove('panel-enter');
      void panel.offsetWidth;
      panel.classList.add('panel-enter');
    }
    if (!opts || !opts.keepScroll) window.scrollTo({ top: 0, behavior: 'auto' });
    setNav(false);
    hero.setActive(btn.dataset.tab === 'answers');
    if (panel) prepareReveals(panel);
  }
  tabs.forEach((btn) => {
    btn.addEventListener('click', () => {
      onTabShown(btn);
      const hash = '#' + btn.dataset.tab;
      if (location.hash !== hash) history.pushState(null, '', hash);
    });
  });
  function activateFromHash(keepScroll) {
    const id = decodeURIComponent(location.hash.replace('#', ''));
    const btn = tabs.find((t) => t.dataset.tab === id);
    if (btn && !btn.classList.contains('active')) {
      btn.click();
      if (keepScroll) return;
    }
  }
  window.addEventListener('popstate', () => {
    const id = location.hash.replace('#', '') || 'answers';
    const btn = tabs.find((t) => t.dataset.tab === id);
    if (btn && !btn.classList.contains('active')) btn.click();
  });

  document.querySelectorAll('[data-goto]').forEach((el) => {
    el.addEventListener('click', (ev) => {
      const btn = tabs.find((t) => t.dataset.tab === el.dataset.goto);
      if (!btn) return;
      ev.preventDefault();
      btn.click();
    });
  });
  document.querySelectorAll('[data-scroll]').forEach((el) => {
    el.addEventListener('click', (ev) => {
      const target = document.getElementById(el.dataset.scroll);
      if (!target) return;
      ev.preventDefault();
      const top = target.getBoundingClientRect().top + window.scrollY - 84;
      window.scrollTo({ top, behavior: reduceMotion ? 'auto' : 'smooth' });
    });
  });

  // --- Footer meta ---
  const footMeta = document.getElementById('foot-meta');
  if (footMeta && D.generated_at) {
    footMeta.textContent =
      'Built ' + new Date(D.generated_at).toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' }) +
      ' from ENTSO-E Transparency Platform data';
  }

  // --- Hero KPIs ---
  const CM = D.comovement || {};
  const kpiHost = document.getElementById('hero-kpis');
  if (kpiHost) {
    const rq1 = (CM.rq1 || {}).variance || {};
    const kpis = [
      { value: (CM.panel || {}).n_zones || D.zones_with_prices, label: 'price zones', digits: 0 },
      { value: (CM.panel || {}).hours, label: 'complete hours', digits: 0 },
      { value: rq1.residual ? 100 * rq1.residual.market : null, label: 'shared Europe-wide', digits: 0, suffix: '%' },
      { value: (CM.rq2 || {}).k, label: 'stable price blocs', digits: 0 },
      { value: ((CM.rq3 || {}).mantel || {}).r, label: 'Mantel r, price vs grid', digits: 2 },
      { value: (CM.rq3 || {}).auc_levels, label: 'AUC, grid adjacency', digits: 2 },
    ].filter((k) => typeof k.value === 'number');
    kpiHost.innerHTML = kpis
      .map((k) =>
        '<div class="kpi"><span class="kpi-value" data-count="' + k.value + '" data-digits="' + k.digits + '" data-suffix="' +
        (k.suffix || '') + '">' + formatNum(k.value, k.digits) + (k.suffix || '') + '</span><span class="kpi-label">' +
        k.label + '</span></div>'
      )
      .join('');
    kpiHost.querySelectorAll('.kpi-value').forEach((el, i) => countUp(el, 250 + i * 90));
  }

  function formatNum(v, digits) {
    return Number(v).toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
  }

  function countUp(el, delay) {
    const target = parseFloat(el.dataset.count);
    const digits = parseInt(el.dataset.digits || '0', 10);
    const suffix = el.dataset.suffix || '';
    if (reduceMotion || !isFinite(target)) return;
    const duration = 1100;
    el.textContent = formatNum(0, digits) + suffix;
    setTimeout(() => {
      const t0 = performance.now();
      function step(now) {
        const p = Math.min(1, (now - t0) / duration);
        const eased = 1 - Math.pow(1 - p, 3);
        el.textContent = formatNum(target * eased, digits) + suffix;
        if (p < 1) requestAnimationFrame(step);
      }
      requestAnimationFrame(step);
    }, delay || 0);
  }

  // Stat cards rendered by app.js: count up plain numbers the first time they scroll into view.
  function prepareStatCount(card) {
    const el = card.querySelector('.value');
    if (!el || el.dataset.counted) return;
    const m = el.textContent.trim().match(/^(-?[\d,]*\.?\d+)(%?)$/);
    if (!m) return;
    el.dataset.counted = '1';
    const raw = m[1].replace(/,/g, '');
    const decimals = raw.includes('.') ? raw.split('.')[1].length : 0;
    el.dataset.count = raw;
    el.dataset.digits = String(decimals);
    el.dataset.suffix = m[2];
    countUp(el, 120);
  }

  // --- Reveal on scroll ---
  const REVEAL = '.stat-card, .answer-block, .explain-card, .chart-wrap, .table-wrap, .rq-answer, .callout-box, .strength-explain, .chart-grid > div';
  const observer = !reduceMotion && 'IntersectionObserver' in window
    ? new IntersectionObserver(
        (entries) => {
          entries.forEach((entry) => {
            if (!entry.isIntersecting) return;
            entry.target.classList.add('in');
            if (entry.target.classList.contains('stat-card')) prepareStatCount(entry.target);
            observer.unobserve(entry.target);
          });
        },
        { rootMargin: '0px 0px -40px 0px', threshold: 0.08 }
      )
    : null;

  function prepareReveals(scope) {
    if (!observer) return;
    let i = 0;
    scope.querySelectorAll(REVEAL).forEach((el) => {
      if (el.dataset.revealed) return;
      el.dataset.revealed = '1';
      el.classList.add('reveal');
      el.style.setProperty('--reveal-delay', Math.min(i++, 6) * 50 + 'ms');
      observer.observe(el);
    });
  }

  // --- Hero network: the real price-coupling graph, drawn on a canvas ---
  const hero = (function () {
    const canvas = document.getElementById('hero-net');
    const noop = { setActive() {}, refreshColors() {} };
    if (!canvas || !canvas.getContext) return noop;
    const ctx = canvas.getContext('2d');
    const layers = (D.map_layers || {}).layers || {};
    const nodes = ((D.map_layers || {}).nodes || []).filter((n) => isFinite(n.lat) && isFinite(n.lon));
    const edges = ((layers.price || {}).strongest || []).concat((layers.flow || {}).all || []);
    if (!nodes.length || !edges.length) return noop;

    let colors = {};
    function refreshColors() {
      colors = {
        node: cssVar('--hero-node'),
        glow: cssVar('--hero-glow'),
        a: cssVar('--hero-edge-a'),
        b: cssVar('--hero-edge-b'),
        pulse: cssVar('--hero-pulse'),
      };
      if (!running) draw(performance.now());
    }

    // Equirectangular projection with a cos(lat) correction, fitted to the canvas.
    const lat0 = 52 * Math.PI / 180;
    const px = (n) => n.lon * Math.cos(lat0);
    const xs = nodes.map(px);
    const ys = nodes.map((n) => n.lat);
    const bounds = { x0: Math.min(...xs), x1: Math.max(...xs), y0: Math.min(...ys), y1: Math.max(...ys) };

    let W = 0;
    let H = 0;
    let points = {};
    let segs = [];
    function layout() {
      const rect = canvas.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      W = rect.width;
      H = rect.height;
      canvas.width = Math.round(W * dpr);
      canvas.height = Math.round(H * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const wide = W > 820;
      // On narrow screens the text sits below the network: keep the drawing inside the
      // space the stylesheet reserves above it (the hero text's top padding).
      const inner = canvas.parentElement.querySelector('.hero-inner');
      const reserved = inner ? parseFloat(getComputedStyle(inner).paddingTop) : H * 0.35;
      const box = wide
        ? { x: W * 0.54, y: H * 0.07, w: W * 0.43, h: H * 0.86 }
        : { x: W * 0.08, y: 18, w: W * 0.84, h: Math.max(80, reserved - 40) };
      const sx = box.w / (bounds.x1 - bounds.x0);
      const sy = box.h / (bounds.y1 - bounds.y0);
      const s = Math.min(sx, sy);
      const ox = box.x + (box.w - (bounds.x1 - bounds.x0) * s) / 2;
      const oy = box.y + (box.h - (bounds.y1 - bounds.y0) * s) / 2;
      points = {};
      nodes.forEach((n) => {
        points[n.id] = { x: ox + (px(n) - bounds.x0) * s, y: oy + (bounds.y1 - n.lat) * s };
      });
      segs = edges
        .map((e) => {
          const a = points[e.from];
          const b = points[e.to];
          if (!a || !b) return null;
          return { a, b, w: Math.max(0.15, e.norm || 0), phase: Math.random(), speed: 0.05 + Math.random() * 0.09 };
        })
        .filter(Boolean);
    }

    function draw(now) {
      if (!W) return;
      const t = now / 1000;
      ctx.clearRect(0, 0, W, H);
      ctx.lineCap = 'round';
      segs.forEach((s) => {
        const g = ctx.createLinearGradient(s.a.x, s.a.y, s.b.x, s.b.y);
        g.addColorStop(0, colors.a);
        g.addColorStop(1, colors.b);
        ctx.strokeStyle = g;
        ctx.globalAlpha = 0.12 + s.w * 0.4;
        ctx.lineWidth = 0.6 + s.w * 1.4;
        ctx.beginPath();
        ctx.moveTo(s.a.x, s.a.y);
        ctx.lineTo(s.b.x, s.b.y);
        ctx.stroke();
      });
      if (!reduceMotion) {
        ctx.fillStyle = colors.pulse;
        segs.forEach((s) => {
          if (s.w < 0.45) return;
          const p = (s.phase + t * s.speed) % 1;
          const x = s.a.x + (s.b.x - s.a.x) * p;
          const y = s.a.y + (s.b.y - s.a.y) * p;
          ctx.globalAlpha = Math.sin(p * Math.PI) * 0.9;
          ctx.beginPath();
          ctx.arc(x, y, 1.6, 0, Math.PI * 2);
          ctx.fill();
        });
      }
      Object.keys(points).forEach((id, i) => {
        const p = points[id];
        const breathe = reduceMotion ? 0.5 : 0.5 + 0.5 * Math.sin(t * 1.4 + i * 0.7);
        ctx.globalAlpha = 0.18 + breathe * 0.22;
        ctx.fillStyle = colors.glow;
        ctx.beginPath();
        ctx.arc(p.x, p.y, 5 + breathe * 3, 0, Math.PI * 2);
        ctx.fill();
        ctx.globalAlpha = 0.95;
        ctx.fillStyle = colors.node;
        ctx.beginPath();
        ctx.arc(p.x, p.y, 2.1, 0, Math.PI * 2);
        ctx.fill();
      });
      ctx.globalAlpha = 1;
    }

    let running = false;
    let visible = true;
    let active = true;
    function loop(now) {
      if (!running) return;
      draw(now);
      requestAnimationFrame(loop);
    }
    function sync() {
      const should = !reduceMotion && visible && active && !document.hidden;
      if (should && !running) {
        running = true;
        requestAnimationFrame(loop);
      } else if (!should) {
        running = false;
      }
    }
    if ('IntersectionObserver' in window) {
      new IntersectionObserver((entries) => {
        visible = entries[0].isIntersecting;
        sync();
      }).observe(canvas);
    }
    document.addEventListener('visibilitychange', sync);
    let resizeTimer = null;
    window.addEventListener('resize', () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        layout();
        draw(performance.now());
      }, 120);
    });

    layout();
    refreshColors();
    draw(performance.now());
    sync();
    return {
      setActive(on) {
        active = on;
        if (on) {
          layout();
          draw(performance.now());
        }
        sync();
      },
      refreshColors,
    };
  })();

  // --- Start: honour a deep link, then prepare reveals on the visible panel ---
  if (location.hash && tabIds.includes(location.hash.slice(1))) {
    activateFromHash(true);
  } else {
    const first = document.querySelector('.panel.active');
    if (first) prepareReveals(first);
  }
})();
