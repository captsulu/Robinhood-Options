/**
 * StockScreenCore.js
 * Core class definition for the Stock Screen tab:
 * constructor, init, data loading, filters, sort, pagination, table rendering.
 *
 * Extended by:
 *   StockScreenModal.js  — openModal / closeModal / chart
 *   StockScreenScan.js   — triggerScan / stopScan / progress polling
 *
 * Depends on: app.grades (GradeManager), fmtMoney(), fmtTime()
 */
class StockScreenManager {
  /** @param {MonitorApp} app */
  constructor(app) {
    this.app = app;

    // ── Filter / sort state ──────────────────────────────────────
    this._query    = '';
    this._grade    = '';
    this._optionsOnly      = true;
    this._maxPrice         = null;
    this._sortCol          = 'score';
    this._sortDir          = 'desc';
    this._page             = 1;
    this._perPage          = 100;
    this._total            = 0;
    this._coveredCallActive = false;

    // Typeahead debounce timer
    this._searchTimer  = null;
    // Scan-progress poll interval id
    this._pollInterval = null;
    // Finished-at sentinel to avoid double-reload
    this._lastFinish   = null;

    // In-memory cache: symbol → stock row (populated from /api/stock-universe)
    // Lets openModal populate instantly without a round-trip
    this._stockData = {};

    // Active Chart.js instance in the detail modal
    this._modalChart = null;
  }

  // ── Bootstrap ────────────────────────────────────────────────────

  /** Called once when the Stock Screen tab is first activated. */
  init() {
    this.loadStats();
    this.load();
    this._startProgressPoll();
  }

  // ── Data loading ─────────────────────────────────────────────────

  /** Fetch and render the current page of stocks. */
  load() {
    const params = new URLSearchParams({
      sort:     this._sortCol,
      dir:      this._sortDir,
      page:     this._page,
      per_page: this._perPage,
    });
    if (this._query)         params.set('q',           this._query);
    if (this._grade)         params.set('grade',        this._grade);
    if (this._maxPrice)      params.set('max_price',    this._maxPrice);
    if (!this._optionsOnly)  params.set('options_only', 'false');

    fetch(`/api/stock-universe?${params}`)
      .then(r => r.json())
      .then(data => {
        this._total = data.total || 0;
        this._renderTable(data.stocks || []);
        this._renderPagination();
        this._updateResultCount();
      })
      .catch(e => console.error('StockScreenManager.load:', e));
  }

  /** Fetch and display grade-distribution stats in the stats bar. */
  loadStats() {
    fetch('/api/stock-universe/stats')
      .then(r => r.json())
      .then(s => {
        const el = document.getElementById('ssStatsLabel');
        if (!el) return;
        if (!s.total) { el.textContent = 'No stocks scanned yet'; return; }
        const byGrade = s.by_grade || {};
        const parts   = ['A','B','C','D','F']
          .filter(g => byGrade[g])
          .map(g => `${g}:${byGrade[g]}`);
        const when = s.last_updated ? ' · Updated ' + fmtTime(s.last_updated) : '';
        el.textContent =
          `${s.total.toLocaleString()} stocks (${parts.join(' | ')})${when}`;
      })
      .catch(() => {});
  }

  // ── Search ───────────────────────────────────────────────────────

  /** Debounced typeahead — wire to the search input's oninput. */
  onSearch(value) {
    clearTimeout(this._searchTimer);
    this._searchTimer = setTimeout(() => {
      this._query = value.trim();
      this._page  = 1;
      this.load();
    }, 280);
  }

  // ── Filters ──────────────────────────────────────────────────────

  setGrade(g) {
    this._coveredCallActive = false;
    this._grade = g;
    this._page  = 1;
    this._syncChips('grade', g);
    this._syncCoveredCallBtn();
    this.load();
  }

  setMaxPrice(p) {
    this._coveredCallActive = false;
    this._maxPrice = p === '' ? null : Number(p);
    this._page     = 1;
    this._syncChips('price', p);
    this._syncCoveredCallBtn();
    this.load();
  }

  toggleOptionsOnly() {
    this._optionsOnly = !this._optionsOnly;
    this._page = 1;
    document.getElementById('ssOptionsOnlyBtn')
      ?.classList.toggle('ss-preset-active', this._optionsOnly);
    this.load();
  }

  /** Preset: Grade A, Price ≤ $500. */
  toggleCoveredCallPreset() {
    this._coveredCallActive = !this._coveredCallActive;
    if (this._coveredCallActive) {
      this._grade = 'A'; this._maxPrice = 500;
    } else {
      this._grade = ''; this._maxPrice = null;
    }
    this._page = 1;
    this._syncChips('grade', this._grade);
    this._syncChips('price', this._maxPrice ? String(this._maxPrice) : '');
    this._syncCoveredCallBtn();
    this.load();
  }

  // ── Sort / pagination ────────────────────────────────────────────

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

  goToPage(p) {
    const max = Math.ceil(this._total / this._perPage) || 1;
    this._page = Math.max(1, Math.min(p, max));
    this.load();
  }

  // ── Private: rendering ───────────────────────────────────────────

  _renderTable(stocks) {
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
    const price    = s.current_price != null ? fmtMoney(s.current_price) : '—';
    const mos      = s.margin_of_safety != null
      ? `<span class="${s.margin_of_safety >= 30 ? 'gs-pos' : s.margin_of_safety >= 0 ? 'gs-warn' : 'gs-neg'}">`
        + (s.margin_of_safety >= 0 ? '+' : '') + s.margin_of_safety.toFixed(1) + '%</span>'
      : '—';
    const pe  = s.pe_ratio != null ? s.pe_ratio.toFixed(1) + '×' : '—';
    const pb  = s.pb_ratio != null ? s.pb_ratio.toFixed(2) + '×' : '—';
    const fcf = s.ttm_fcf  != null
      ? `<span class="${s.ttm_fcf > 0 ? 'gs-pos' : 'gs-neg'}">${s.ttm_fcf > 0 ? '✓' : '✗'}</span>`
      : '—';
    const exch = s.exchange
      ? `<span style="font-size:11px;color:var(--muted)">${s.exchange}</span>` : '';

    return `<tr class="ss-row" onclick="window.stockScreen.openModal('${s.symbol}')">
      <td class="sym-col"><span class="ss-ticker">${s.symbol}</span></td>
      <td class="ss-name-col">${s.company_name || ''}</td>
      <td class="num-col">${price}</td>
      <td>
        <button class="grade-btn ${gradeCls}"
                onclick="event.stopPropagation();window.stockScreen.openModal('${s.symbol}')"
                title="Graham Grade: ${s.grade || '?'}">${s.grade || '?'}</button>
      </td>
      <td class="num-col">${s.score != null ? s.score.toFixed(1) : '—'}</td>
      <td class="num-col">${mos}</td>
      <td class="num-col">${pe}</td>
      <td class="num-col">${pb}</td>
      <td class="num-col">${fcf}</td>
      <td>${exch}</td>
    </tr>`;
  }

  _renderPagination() {
    const max  = Math.ceil(this._total / this._perPage) || 1;
    const html = max <= 1 ? '' : this._buildPaginationHTML(this._page, max);
    ['ssPaginationTop','ssPaginationBottom'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.innerHTML = html;
    });
  }

  _buildPaginationHTML(cur, max) {
    const add = (lbl, pg, dis, act) =>
      `<button class="ss-page-btn${act ? ' active' : ''}" ${dis ? 'disabled' : ''}
               onclick="window.stockScreen.goToPage(${pg})">${lbl}</button>`;
    const p = [];
    p.push(add('«', 1, cur===1, false));
    p.push(add('‹', cur-1, cur===1, false));
    const lo = Math.max(1, cur-2), hi = Math.min(max, cur+2);
    if (lo > 1) { p.push(add('1',1,false,false)); if (lo>2) p.push('<span class="ss-ellipsis">…</span>'); }
    for (let i=lo; i<=hi; i++) p.push(add(i,i,false,i===cur));
    if (hi < max) { if (hi<max-1) p.push('<span class="ss-ellipsis">…</span>'); p.push(add(max,max,false,false)); }
    p.push(add('›', cur+1, cur===max, false));
    p.push(add('»', max, cur===max, false));
    return p.join('');
  }

  _updateResultCount() {
    const el = document.getElementById('ssResultCount');
    if (!el) return;
    if (this._total === 0) { el.textContent = 'No results'; return; }
    const start = (this._page - 1) * this._perPage + 1;
    const end   = Math.min(this._page * this._perPage, this._total);
    el.textContent =
      `Showing ${start.toLocaleString()}–${end.toLocaleString()} of ${this._total.toLocaleString()} stocks`;
  }

  _syncChips(type, activeValue) {
    const attr = type === 'grade' ? 'data-grade' : 'data-price';
    const val  = String(activeValue ?? '');
    document.querySelectorAll(`.ss-chip[${attr}]`).forEach(c =>
      c.classList.toggle('ss-chip-active', c.getAttribute(attr) === val)
    );
  }

  _syncCoveredCallBtn() {
    document.getElementById('ssCoveredCallBtn')
      ?.classList.toggle('ss-preset-active', this._coveredCallActive);
  }

  _updateSortArrows() {
    document.querySelectorAll('#ssTable .ss-th-sort').forEach(th => {
      const arrow = th.querySelector('.sort-arrow');
      if (!arrow) return;
      arrow.textContent = th.getAttribute('data-col') === this._sortCol
        ? (this._sortDir === 'desc' ? ' ▼' : ' ▲') : '';
    });
  }
}
