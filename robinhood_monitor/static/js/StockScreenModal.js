/**
 * StockScreenModal.js
 * Prototype extensions for StockScreenManager — modal open/close/render.
 * Must load AFTER StockScreenCore.js.
 *
 * Methods added:
 *   openModal(symbol)   — open enriched detail modal
 *   closeModal(evt)     — close on button or overlay click
 *   _buildMarketSnap(d) — builds the market-data pill strip HTML
 *   _drawModalChart(prices) — renders 30-day Chart.js line chart
 */

StockScreenManager.prototype.openModal = function(symbol) {
  const modal   = document.getElementById('ssModal');
  const symEl   = document.getElementById('ssModalSymbol');
  const nameEl  = document.getElementById('ssModalName');
  const gradeEl = document.getElementById('ssModalGrade');
  const bodyEl  = document.getElementById('ssModalBody');

  // Reset header
  symEl.textContent   = symbol;
  nameEl.textContent  = '';
  gradeEl.className   = 'gs-grade-big grade-loading';
  gradeEl.textContent = '…';
  modal.classList.remove('hidden');
  document.body.style.overflow = 'hidden';

  // Skeleton body
  bodyEl.innerHTML = `
    <div id="ssModalMarket" class="ss-modal-market-loading">
      <span style="color:var(--muted);font-size:12px">Fetching market data…</span>
    </div>
    <div class="ss-modal-chart-wrap">
      <canvas id="ssModalChart"></canvas>
    </div>
    <div id="ssModalGraham" class="ss-modal-graham">
      <p style="color:var(--muted);text-align:center;padding:24px 0">Loading fundamentals…</p>
    </div>`;

  // ── Fetch market data + 30-day chart ─────────────────────────────
  fetch(`/api/stock-detail/${symbol}`)
    .then(r => r.json())
    .then(d => {
      const el = document.getElementById('ssModalMarket');
      if (el) el.outerHTML = this._buildMarketSnap(d);
      if (d.prices && d.prices.length > 1) this._drawModalChart(d.prices);
    })
    .catch(() => {
      const el = document.getElementById('ssModalMarket');
      if (el) el.textContent = '';
    });

  // ── Graham fundamentals ─────────────────────────────────────────
  const row = this._stockData[symbol];

  const setGraham = (data) => {
    const el = document.getElementById('ssModalGraham');
    if (!el) return;
    nameEl.textContent = data.name || row?.company_name || '';
    if (data.error) {
      gradeEl.className   = 'gs-grade-big grade-err';
      gradeEl.textContent = '!';
      el.innerHTML = `<p class="gs-error">⚠ ${data.error}</p>`;
    } else {
      gradeEl.className   = `gs-grade-big ${this.app.grades.gradeColor(data.grade)}`;
      gradeEl.textContent = data.grade || '?';
      el.innerHTML        = this.app.grades._buildSidebarBody(symbol, data);
    }
  };

  if (row && !row._partial) {
    // Full cache hit — no network call needed
    setGraham({
      name: row.company_name, grade: row.grade, score: row.score,
      current_price: row.current_price, intrinsic_value: row.intrinsic_value,
      margin_of_safety: row.margin_of_safety, ath_52w: row.ath_52w,
      low_52w: row.low_52w, pct_of_ath: row.pct_of_ath,
      eps_ttm: row.eps_ttm, bvps: row.bvps, pe_ratio: row.pe_ratio,
      pb_ratio: row.pb_ratio, ttm_fcf: row.ttm_fcf,
      fcf_per_share: row.fcf_per_share, cached_at: row.last_updated,
      error: row.error,
    });
  } else {
    // Partial cache (from put/CC screen) or nothing — show what we have, then fetch
    if (row) {
      nameEl.textContent  = row.company_name || '';
      gradeEl.className   = `gs-grade-big ${this.app.grades.gradeColor(row.grade)}`;
      gradeEl.textContent = row.grade || '?';
    }
    fetch(`/api/grade/${symbol}`)
      .then(r => r.json())
      .then(data => setGraham(data))
      .catch(() => setGraham({ error: 'Could not load fundamentals.' }));
  }
};

StockScreenManager.prototype.closeModal = function(evt) {
  if (evt && evt.target !== document.getElementById('ssModal')) return;
  document.getElementById('ssModal').classList.add('hidden');
  document.body.style.overflow = '';
};

StockScreenManager.prototype._buildMarketSnap = function(d) {
  const fmtMon = (n) => n != null
    ? '$' + Number(n).toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2}) : '—';
  const fmtVol = (n) => {
    if (n == null) return '—';
    if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
    if (n >= 1e3) return (n / 1e3).toFixed(0) + 'K';
    return String(n);
  };
  const chgCls = d.change_pct == null ? '' : d.change_pct >= 0 ? 'gs-pos' : 'gs-neg';
  const chgLbl = d.change_pct != null
    ? `<span class="${chgCls}">${d.change_pct >= 0 ? '+' : ''}${d.change_pct.toFixed(2)}%</span>`
    : '—';

  const metrics = [
    { label: 'Mkt Cap',    value: d.market_cap || '—' },
    { label: 'Last',       value: fmtMon(d.last_price) },
    { label: 'Day Chg',    value: chgLbl, raw: true },
    { label: 'Volume',     value: fmtVol(d.volume) },
    { label: 'Avg Vol',    value: fmtVol(d.avg_volume) },
    { label: '52w High',   value: fmtMon(d.high_52w) },
    { label: '52w Low',    value: fmtMon(d.low_52w) },
    { label: 'Prev Close', value: fmtMon(d.prev_close) },
  ];
  const pills = metrics.map(m =>
    `<div class="ss-modal-metric">
       <span class="ss-modal-metric-label">${m.label}</span>
       <span class="ss-modal-metric-val">${m.value}</span>
     </div>`).join('');
  return `<div id="ssModalMarket" class="ss-modal-market">${pills}</div>`;
};

StockScreenManager.prototype._drawModalChart = function(prices) {
  if (this._modalChart) { this._modalChart.destroy(); this._modalChart = null; }
  const canvas = document.getElementById('ssModalChart');
  if (!canvas) return;

  const labels = prices.map(p => p.date);
  const values = prices.map(p => p.close);
  const up     = values[values.length - 1] >= values[0];
  const color  = up ? '#3fb950' : '#f85149';
  const fill   = up ? 'rgba(63,185,80,0.12)' : 'rgba(248,81,73,0.12)';

  this._modalChart = new Chart(canvas, {
    type: 'line',
    data: {
      labels,
      datasets: [{ data: values, borderColor: color, backgroundColor: fill,
        borderWidth: 2, pointRadius: 0, fill: true, tension: 0.3 }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      animation: { duration: 400 },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => ' $' + ctx.parsed.y.toFixed(2) } },
      },
      scales: {
        x: { ticks: { color: '#8b949e', maxTicksLimit: 6, font: { size: 10 } },
             grid:  { color: 'rgba(48,54,61,0.8)' } },
        y: { position: 'right',
             ticks: { color: '#8b949e', font: { size: 10 },
                      callback: v => '$' + v.toFixed(0) },
             grid:  { color: 'rgba(48,54,61,0.8)' } },
      },
    },
  });
};
