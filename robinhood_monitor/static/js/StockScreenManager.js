/**
 * StockScreenManager
 * Manages the Stock Screen tab: typeahead search, filter chips, sortable
 * paginated table, scan-progress polling, and a detail popup modal that
 * reuses the GradeManager sidebar HTML builder.
 *
 * Depends on: app.grades (GradeManager), fmtMoney(), fmtTime()
 */
class StockScreenManager {
  /** @param {MonitorApp} app */
  constructor(app) {
    this.app = app;

    // ── Filter / sort state ──────────────────────────────────────
    this._query    = '';
    this._grade    = '';       // '' = all
    this._optionsOnly = true;   // default: only show stocks with listed options
    this._maxPrice = null;
    this._sortCol  = 'score';
    this._sortDir  = 'desc';
    this._page     = 1;
    this._perPage  = 100;
    this._total    = 0;

    // Typeahead debounce timer
    this._searchTimer = null;

    // Scan-progress polling interval id
    this._pollInterval = null;

    // Covered-call preset active flag
    this._coveredCallActive = false;

    // In-memory cache: symbol → row dict from /api/stock-universe
    // Populated in _renderTable so openModal can use it instantly.
    this._stockData = {};

    // Active Chart.js instance in the detail modal (destroyed on each re-open)
    this._modalChart = null;
  }

  // ── Public API ───────────────────────────────────────────────────

  /** Called when the Stock Screen tab is first activated. */
  init() {
    this.loadStats();
    this.load();
    this._startProgressPoll();
  }

  /** Fetch and render the current page of results. */
  load() {
    const params = new URLSearchParams({
      sort:     this._sortCol,
      dir:      this._sortDir,
      page:     this._page,
      per_page: this._perPage,
    });
    if (this._query)    params.set('q',         this._query);
    if (this._grade)    params.set('grade',      this._grade);
    if (this._maxPrice) params.set('max_price',  this._maxPrice);
    if (!this._optionsOnly)  params.set('options_only', 'false');

    fetch(`/api/stock-universe?${params}`)
      .then(r => r.json())
      .then(data => {
        this._total = data.total || 0;
        this._renderTable(data.stocks || []);
        this._renderPagination();
        this._updateResultCount();
      })
      .catch(e => console.error('StockScreenManager.load error:', e));
  }

  /** Fetch and display grade distribution stats. */
  loadStats() {
    fetch('/api/stock-universe/stats')
      .then(r => r.json())
      .then(s => {
        const el = document.getElementById('ssStatsLabel');
        if (!el) return;
        if (!s.total) {
          el.textContent = 'No stocks scanned yet';
          return;
        }
        const byGrade = s.by_grade || {};
        const parts   = ['A','B','C','D','F']
          .filter(g => byGrade[g])
          .map(g => `${g}:${byGrade[g]}`);
        const when = s.last_updated
          ? ' · Updated ' + fmtTime(s.last_updated)
          : '';
        el.textContent =
          `${s.total.toLocaleString()} stocks (${parts.join(' | ')})${when}`;
      })
      .catch(() => {});
  }

  // ── Search ───────────────────────────────────────────────────────

  /** Debounced typeahead — called on every keystroke. */
  onSearch(value) {
    clearTimeout(this._searchTimer);
    this._searchTimer = setTimeout(() => {
      this._query = value.trim();
      this._page  = 1;
      this.load();
    }, 280);
  }

  // ── Filter setters ───────────────────────────────────────────────

  /** @param {string} g - grade letter or '' for all */
  setGrade(g) {
    this._coveredCallActive = false;
    this._grade    = g;
    this._page     = 1;
    this._syncChips('grade', g);
    this._syncCoveredCallBtn();
    this.load();
  }

  /** @param {number|string} p - max price or '' for any */
  setMaxPrice(p) {
    this._coveredCallActive = false;
    this._maxPrice = p === '' ? null : Number(p);
    this._page     = 1;
    this._syncChips('price', p);
    this._syncCoveredCallBtn();
    this.load();
  }

  /** Toggle the "Options Only" filter (default on). */
  toggleOptionsOnly() {
    this._optionsOnly = !this._optionsOnly;
    this._page = 1;
    const btn = document.getElementById('ssOptionsOnlyBtn');
    if (btn) btn.classList.toggle('ss-preset-active', this._optionsOnly);
    this.load();
  }

  /**
   * Toggle the "Covered Call Picks" preset:
   * Grade = A, Max Price = $500.
   */
  toggleCoveredCallPreset() {
    this._coveredCallActive = !this._coveredCallActive;
    if (this._coveredCallActive) {
      this._grade    = 'A';
      this._maxPrice = 500;
    } else {
      this._grade    = '';
      this._maxPrice = null;
    }
    this._page = 1;
    this._syncChips('grade', this._grade);
    this._syncChips('price', this._maxPrice ? String(this._maxPrice) : '');
    this._syncCoveredCallBtn();
    this.load();
  }

  // ── Sort ─────────────────────────────────────────────────────────

  /** Toggle sort direction if same column, otherwise sort desc. */
  setSort(col) {
    if (this._sortCol === col) {
      this._sortDir = this._sortDir === 'desc' ? 'asc' : 'desc';
    } else {
      this._sortCol = col;
      this._sortDir = 'desc';
    }
    this._page = 1;
    this._updateSortArrows();
    this.load();
  }

  // ── Pagination ───────────────────────────────────────────────────

  goToPage(p) {
    const maxPage = Math.ceil(this._total / this._perPage) || 1;
    this._page = Math.max(1, Math.min(p, maxPage));
    this.load();
  }

  // ── Detail modal ─────────────────────────────────────────────────

  /**
   * Open the enriched detail modal for any stock symbol.
   *
   * Layout (top → bottom):
   *   Market snapshot strip  — market cap, volume, 52w hi/lo, change% (from /api/stock-detail)
   *   30-day price chart     — Chart.js line, coloured green/red by direction
   *   Graham fundamentals    — existing sidebar content (from cache or /api/grade)
   *
   * Graham data: fast path from _stockData cache (full rows from stock screen),
   *   partial-row fast path (name + grade only, from put screen cache),
   *   or slow live fetch from /api/grade if not cached at all.
   */
  openModal(symbol) {
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

    // Skeleton: market strip + chart placeholder + graham placeholder
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

    // ── Market data + chart (always fresh) ────────────────────────────
    fetch(`/api/stock-detail/${symbol}`)
      .then(r => r.json())
      .then(d => {
        const marketEl = document.getElementById('ssModalMarket');
        if (marketEl) marketEl.outerHTML = this._buildMarketSnap(d);
        if (d.prices && d.prices.length > 1) this._drawModalChart(d.prices);
      })
      .catch(() => {
        const marketEl = document.getElementById('ssModalMarket');
        if (marketEl) marketEl.textContent = '';
      });

    // ── Graham fundamentals ───────────────────────────────────────────
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
        el.innerHTML = this.app.grades._buildSidebarBody(symbol, data);
      }
    };

    if (row && !row._partial) {
      // Full cache hit — populate instantly
      setGraham({
        name:             row.company_name,
        grade:            row.grade,
        score:            row.score,
        current_price:    row.current_price,
        intrinsic_value:  row.intrinsic_value,
        margin_of_safety: row.margin_of_safety,
        ath_52w:          row.ath_52w,
        low_52w:          row.low_52w,
        pct_of_ath:       row.pct_of_ath,
        eps_ttm:          row.eps_ttm,
        bvps:             row.bvps,
        pe_ratio:         row.pe_ratio,
        pb_ratio:         row.pb_ratio,
        ttm_fcf:          row.ttm_fcf,
        fcf_per_share:    row.fcf_per_share,
        cached_at:        row.last_updated,
        error:            row.error,
      });
    } else {
      // Partial cache (put screen row) or no cache — set header from partial, fetch rest
      if (row) {
        nameEl.textContent  = row.company_name || '';
        gradeEl.className   = `gs-grade-big ${this.app.grades.gradeColor(row.grade)}`;
        gradeEl.textContent = row.grade || '?';
      }
      fetch(`/api/grade/${symbol}`)
        .then(r => r.json())
        .then(data => setGraham(data))
        .catch(() => setGraham({ error: 'Could not load fundamentals — check server.' }));
    }
  }

  /** Close the detail modal. Pass a click event to allow overlay-click-to-close. */
  closeModal(evt) {
    if (evt && evt.target !== document.getElementById('ssModal')) return;
    document.getElementById('ssModal').classList.add('hidden');
    document.body.style.overflow = '';
  }

  // ── Private: market snapshot strip ───────────────────────────────

  _buildMarketSnap(d) {
    const fmt     = (n, dec=0) => n != null ? Number(n).toLocaleString('en-US', {maximumFractionDigits: dec}) : '—';
    const fmtMon  = (n) => n != null ? '$' + Number(n).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2}) : '—';
    const fmtVol  = (n) => {
      if (n == null) return '—';
      if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
      if (n >= 1e3) return (n / 1e3).toFixed(0) + 'K';
      return String(n);
    };
    const chgCls  = d.change_pct == null ? '' : d.change_pct >= 0 ? 'gs-pos' : 'gs-neg';
    const chgLbl  = d.change_pct != null
      ? `<span class="${chgCls}">${d.change_pct >= 0 ? '+' : ''}${d.change_pct.toFixed(2)}%</span>`
      : '—';

    const metrics = [
      { label: 'Mkt Cap',    value: d.market_cap  || '—' },
      { label: 'Last',       value: fmtMon(d.last_price) },
      { label: 'Day Chg',    value: chgLbl, raw: true },
      { label: 'Volume',     value: fmtVol(d.volume) },
      { label: 'Avg Vol',    value: fmtVol(d.avg_volume) },
      { label: '52w High',   value: fmtMon(d.high_52w) },
      { label: '52w Low',    value: fmtMon(d.low_52w) },
      { label: 'Prev Close', value: fmtMon(d.prev_close) },
    ];

    const pills = metrics.map(m => `
      <div class="ss-modal-metric">
        <span class="ss-modal-metric-label">${m.label}</span>
        <span class="ss-modal-metric-val">${m.raw ? m.value : m.value}</span>
      </div>`).join('');

    return `<div id="ssModalMarket" class="ss-modal-market">${pills}</div>`;
  }

  // ── Private: 30-day chart ─────────────────────────────────────────

  _drawModalChart(prices) {
    // Destroy any previous chart instance to avoid "canvas already in use" error
    if (this._modalChart) {
      this._modalChart.destroy();
      this._modalChart = null;
    }
    const canvas = document.getElementById('ssModalChart');
    if (!canvas) return;

    const labels = prices.map(p => p.date);
    const values = prices.map(p => p.close);
    const first  = values[0];
    const last   = values[values.length - 1];
    const up     = last >= first;
    const color  = up ? '#3fb950' : '#f85149';
    const fill   = up ? 'rgba(63,185,80,0.12)' : 'rgba(248,81,73,0.12)';

    this._modalChart = new Chart(canvas, {
      type: 'line',
      data: {
        labels,
        datasets: [{
          data:            values,
          borderColor:     color,
          backgroundColor: fill,
          borderWidth:     2,
          pointRadius:     0,
          fill:            true,
          tension:         0.3,
        }],
      },
      options: {
        responsive:          true,
        maintainAspectRatio: false,
        animation:           { duration: 400 },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: ctx => ' $' + ctx.parsed.y.toFixed(2),
            },
          },
        },
        scales: {
          x: {
            ticks: { color: '#8b949e', maxTicksLimit: 6, font: { size: 10 } },
            grid:  { color: 'rgba(48,54,61,0.8)' },
          },
          y: {
            position: 'right',
            ticks:    { color: '#8b949e', font: { size: 10 },
                        callback: v => '$' + v.toFixed(0) },
            grid:     { color: 'rgba(48,54,61,0.8)' },
          },
        },
      },
    });
  }

  // ── Scan control ─────────────────────────────────────────────────

  triggerScan(btn) {
    if (btn) { btn.disabled = true; btn.textContent = '⏳ Starting…'; }
    fetch('/api/stock-universe/scan', { method: 'POST' })
      .then(r => r.json())
      .then(data => {
        if (!data.success) {
          alert(data.message || 'Could not start scan');
          if (btn) { btn.disabled = false; btn.textContent = '⚡ Run Full Scan'; }
        }
        this._startProgressPoll();
      })
      .catch(() => {
        if (btn) { btn.disabled = false; btn.textContent = '⚡ Run Full Scan'; }
      });
  }

  stopScan() {
    fetch('/api/stock-universe/scan/stop', { method: 'POST' });
  }

  // ── Private: rendering ───────────────────────────────────────────

  _renderTable(stocks) {
    // Cache every visible row so openModal can populate instantly.
    stocks.forEach(s => { this._stockData[s.symbol] = s; });

    const tbody = document.getElementById('ssBody');
    if (!stocks.length) {
      tbody.innerHTML = '<tr><td colspan="10" class="empty-msg">'
        + (this._total === 0
            ? 'No stocks in the database yet — run a scan first.'
            : 'No stocks match the current filters.')
        + '</td></tr>';
      return;
    }
    tbody.innerHTML = stocks.map(s => this._buildRow(s)).join('');
    this._updateSortArrows();
  }

  _buildRow(s) {
    const gradeCls = this.app.grades.gradeColor(s.grade);
    const price    = s.current_price != null ? fmtMoney(s.current_price) : '\u2014';
    const mos      = s.margin_of_safety != null
      ? `<span class="${s.margin_of_safety >= 30 ? 'gs-pos' : s.margin_of_safety >= 0 ? 'gs-warn' : 'gs-neg'}">`
        + (s.margin_of_safety >= 0 ? '+' : '') + s.margin_of_safety.toFixed(1) + '%</span>'
      : '\u2014';
    const pe  = s.pe_ratio  != null ? s.pe_ratio.toFixed(1)  + '\u00d7' : '\u2014';
    const pb  = s.pb_ratio  != null ? s.pb_ratio.toFixed(2)  + '\u00d7' : '\u2014';
    const fcf = s.ttm_fcf   != null
      ? `<span class="${s.ttm_fcf > 0 ? 'gs-pos' : 'gs-neg'}">${s.ttm_fcf > 0 ? '\u2713' : '\u2717'}</span>`
      : '\u2014';
    const exch = s.exchange ? `<span style="font-size:11px;color:var(--muted)">${s.exchange}</span>` : '';

    return `<tr class="ss-row" onclick="window.stockScreen.openModal('${s.symbol}')">
      <td class="sym-col">
        <span class="ss-ticker">${s.symbol}</span>
      </td>
      <td class="ss-name-col">${s.company_name || ''}</td>
      <td class="num-col">${price}</td>
      <td>
        <button class="grade-btn ${gradeCls}"
                onclick="event.stopPropagation();window.stockScreen.openModal('${s.symbol}')"
                title="Graham Grade: ${s.grade || '?'}">${s.grade || '?'}</button>
      </td>
      <td class="num-col">${s.score != null ? s.score.toFixed(1) : '\u2014'}</td>
      <td class="num-col">${mos}</td>
      <td class="num-col">${pe}</td>
      <td class="num-col">${pb}</td>
      <td class="num-col">${fcf}</td>
      <td>${exch}</td>
    </tr>`;
  }

  _renderPagination() {
    const maxPage = Math.ceil(this._total / this._perPage) || 1;
    if (maxPage <= 1) {
      ['ssPaginationTop', 'ssPaginationBottom'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.innerHTML = '';
      });
      return;
    }

    const p    = this._page;
    const html = this._buildPaginationHTML(p, maxPage);
    ['ssPaginationTop', 'ssPaginationBottom'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.innerHTML = html;
    });
  }

  _buildPaginationHTML(current, maxPage) {
    const pages = [];
    const add   = (label, page, disabled, active) =>
      `<button class="ss-page-btn${active ? ' active' : ''}"
               ${disabled ? 'disabled' : ''}
               onclick="window.stockScreen.goToPage(${page})">${label}</button>`;

    pages.push(add('\u00ab', 1, current === 1, false));
    pages.push(add('\u2039', current - 1, current === 1, false));

    const lo = Math.max(1,       current - 2);
    const hi = Math.min(maxPage, current + 2);
    if (lo > 1)       { pages.push(add('1', 1, false, false)); if (lo > 2) pages.push('<span class="ss-ellipsis">\u2026</span>'); }
    for (let i = lo; i <= hi; i++) pages.push(add(i, i, false, i === current));
    if (hi < maxPage) { if (hi < maxPage - 1) pages.push('<span class="ss-ellipsis">\u2026</span>'); pages.push(add(maxPage, maxPage, false, false)); }

    pages.push(add('\u203a', current + 1, current === maxPage, false));
    pages.push(add('\u00bb', maxPage,     current === maxPage, false));

    return pages.join('');
  }

  _updateResultCount() {
    const el = document.getElementById('ssResultCount');
    if (!el) return;
    if (this._total === 0) {
      el.textContent = 'No results';
    } else {
      const start = (this._page - 1) * this._perPage + 1;
      const end   = Math.min(this._page * this._perPage, this._total);
      el.textContent = `Showing ${start.toLocaleString()}\u2013${end.toLocaleString()} of ${this._total.toLocaleString()} stocks`;
    }
  }

  _syncChips(type, activeValue) {
    const attr = type === 'grade' ? 'data-grade' : 'data-price';
    const val  = String(activeValue ?? '');
    document.querySelectorAll(`.ss-chip[${attr}]`).forEach(chip => {
      chip.classList.toggle('ss-chip-active', chip.getAttribute(attr) === val);
    });
  }

  _syncCoveredCallBtn() {
    const btn = document.getElementById('ssCoveredCallBtn');
    if (btn) btn.classList.toggle('ss-preset-active', this._coveredCallActive);
  }

  _updateSortArrows() {
    document.querySelectorAll('#ssTable .ss-th-sort').forEach(th => {
      const col   = th.getAttribute('data-col');
      const arrow = th.querySelector('.sort-arrow');
      if (!arrow) return;
      if (col === this._sortCol) {
        arrow.textContent = this._sortDir === 'desc' ? ' \u25bc' : ' \u25b2';
      } else {
        arrow.textContent = '';
      }
    });
  }

  _startProgressPoll() {
    if (this._pollInterval) clearInterval(this._pollInterval);
    this._pollInterval = setInterval(() => this._pollScanStatus(), 3000);
  }

  _pollScanStatus() {
    fetch('/api/stock-universe/scan/status')
      .then(r => r.json())
      .then(p => this._renderScanProgress(p))
      .catch(() => {});
  }

  _renderScanProgress(p) {
    const progressWrap = document.getElementById('ssScanProgress');
    const bar          = document.getElementById('ssScanBar');
    const text         = document.getElementById('ssScanProgressText');
    const statusEl     = document.getElementById('ssScanStatus');
    const scanBtn      = document.getElementById('ssScanBtn');

    if (p.running) {
      progressWrap.classList.remove('hidden');
      const pct = p.total > 0 ? Math.round(p.done / p.total * 100) : 0;
      bar.style.width   = pct + '%';
      text.textContent  = `${p.done.toLocaleString()} / ${p.total.toLocaleString()} (${pct}%)  \u00b7  ${p.current}`;
      if (statusEl) {
        statusEl.className   = 'ss-scan-status ss-scan-running';
        statusEl.textContent = '\u26a1 Scanning\u2026';
      }
      if (scanBtn) { scanBtn.disabled = true; scanBtn.textContent = '\u23f3 Scanning\u2026'; }
    } else {
      progressWrap.classList.add('hidden');
      if (statusEl) statusEl.className = 'ss-scan-status hidden';
      if (scanBtn)  { scanBtn.disabled = false; scanBtn.textContent = '\u26a1 Run Full Scan'; }

      if (p.finished_at && !this._lastFinish) {
        this.loadStats();
        this.load();
      }
      this._lastFinish = p.finished_at;
    }
  }
}
