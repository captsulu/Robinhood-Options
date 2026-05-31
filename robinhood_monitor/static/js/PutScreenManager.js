/**
 * PutScreenManager
 * Manages the Put Screen tab: tier/grade/collateral filter chips, sortable
 * paginated table, scan-progress polling, and news-risk badge display.
 *
 * Tier colours (annualised ROI):
 *   Legendary ≥ 40 %   Epic 30–39 %   Rare 25–29 %   Good 20–24 %
 *
 * Depends on: app.grades (for grade badge colours), fmtMoney(), fmtTime()
 */
class PutScreenManager {
  /** @param {MonitorApp} app */
  constructor(app) {
    this.app = app;

    // ── Filter / sort state ──────────────────────────────────────
    this._tier        = '';
    this._grade       = '';
    this._collateral  = null;
    this._hideRisk    = false;
    this._sortCol     = 'annualised_roi';
    this._sortDir     = 'desc';
    this._page        = 1;
    this._perPage     = 100;
    this._total       = 0;

    this._pollInterval = null;
  }

  // ── Public API ───────────────────────────────────────────────────

  /** Called when the Put Screen tab is first activated. */
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
    if (this._tier)       params.set('tier',       this._tier);
    if (this._grade)      params.set('grade',      this._grade);
    if (this._collateral) params.set('collateral', this._collateral);
    if (this._hideRisk)   params.set('news_risk',  'low');   // exclude high+medium

    fetch(`/api/put-screen?${params}`)
      .then(r => r.json())
      .then(data => {
        this._total = data.total || 0;
        this._renderTable(data.opportunities || []);
        this._renderPagination();
        this._updateResultCount();
      })
      .catch(e => console.error('PutScreenManager.load error:', e));
  }

  /** Fetch and display tier distribution stats. */
  loadStats() {
    fetch('/api/put-screen/stats')
      .then(r => r.json())
      .then(s => {
        const el = document.getElementById('psStatsLabel');
        if (!el) return;
        if (!s.total) {
          el.textContent = 'No opportunities scanned yet';
          return;
        }
        const bt    = s.by_tier || {};
        const order = ['legendary', 'epic', 'rare', 'good'];
        const icons = { legendary: '🏆', epic: '⚡', rare: '💎', good: '✓' };
        const parts = order
          .filter(t => bt[t])
          .map(t => `${icons[t]}${bt[t]}`);
        const riskNote = s.high_risk_count
          ? `  ·  🚨 ${s.high_risk_count} high-risk`
          : '';
        const when = s.last_scan
          ? '  ·  Updated ' + fmtTime(s.last_scan)
          : '';
        el.textContent =
          `${s.total.toLocaleString()} opportunities  (${parts.join('  ')})${riskNote}${when}`;
      })
      .catch(() => {});
  }

  // ── Filters ──────────────────────────────────────────────────────

  setTier(t) {
    this._tier = t;
    this._page = 1;
    this._syncChips('tier', t);
    this.load();
  }

  setGrade(g) {
    this._grade = g;
    this._page  = 1;
    this._syncChips('ps-grade', g);
    this.load();
  }

  setCollateral(c) {
    this._collateral = c === '' ? null : Number(c);
    this._page       = 1;
    this._syncChips('ps-coll', c === '' ? '' : String(c));
    this.load();
  }

  toggleHideRisk() {
    this._hideRisk = !this._hideRisk;
    this._page     = 1;
    const btn = document.getElementById('psHideRiskBtn');
    if (btn) btn.classList.toggle('ss-preset-active', this._hideRisk);
    this.load();
  }

  // ── Sort ─────────────────────────────────────────────────────────

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

  // ── Scan control ─────────────────────────────────────────────────

  triggerScan(btn) {
    if (btn) { btn.disabled = true; btn.textContent = '⏳ Starting…'; }
    const stopBtn = document.getElementById('psStopBtn');
    if (stopBtn) stopBtn.style.display = 'inline-block';
    fetch('/api/put-screen/scan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ grades: ['A', 'B'] }),
    })
      .then(r => r.json())
      .then(data => {
        if (!data.success) {
          alert(data.message || 'Could not start scan');
          if (btn) { btn.disabled = false; btn.textContent = '⚡ Scan Opportunities'; }
          if (stopBtn) stopBtn.style.display = 'none';
        }
        this._startProgressPoll();
      })
      .catch(() => {
        if (btn) { btn.disabled = false; btn.textContent = '⚡ Scan Opportunities'; }
        if (stopBtn) stopBtn.style.display = 'none';
      });
  }

  stopScan() {
    fetch('/api/put-screen/scan/stop', { method: 'POST' });
    const stopBtn = document.getElementById('psStopBtn');
    if (stopBtn) stopBtn.style.display = 'none';
  }

  // ── Private: rendering ───────────────────────────────────────────

  _renderTable(rows) {
    const tbody = document.getElementById('psBody');
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="15" class="empty-msg">'
        + (this._total === 0
            ? 'No opportunities found — run a scan first.'
            : 'No opportunities match the current filters.')
        + '</td></tr>';
      return;
    }

    // Seed the stock screen's cache with partial data so openModal can
    // populate the header (name + grade) instantly without a live fetch.
    if (window.stockScreen) {
      rows.forEach(r => {
        if (!window.stockScreen._stockData[r.symbol]) {
          window.stockScreen._stockData[r.symbol] = {
            company_name:  r.company_name,
            grade:         r.grade,
            current_price: r.current_price,
            _partial:      true,  // tells openModal to still fetch Graham data
          };
        }
      });
    }

    tbody.innerHTML = rows.map(r => this._buildRow(r)).join('');
    this._updateSortArrows();
  }

  _buildRow(r) {
    const tierCls  = `ps-tier-badge ps-tier-${r.tier || 'good'}`;
    const tierIcon = { legendary: '🏆', epic: '⚡', rare: '💎', good: '✓' }[r.tier] || '✓';
    const tierLbl  = r.tier ? r.tier.charAt(0).toUpperCase() + r.tier.slice(1) : 'Good';

    const gradeCls = this.app.grades.gradeColor(r.grade);
    const price    = r.current_price != null ? fmtMoney(r.current_price) : '—';

    // Expiry: "Jun 20"
    const expLbl = r.expiration
      ? new Date(r.expiration + 'T12:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
      : '—';

    // Spread: "40.00 / 35.00"
    const spreadLbl = `${r.short_strike != null ? r.short_strike.toFixed(2) : '?'}`
                    + ` / ${r.long_strike != null ? r.long_strike.toFixed(2) : '?'}`;

    const collLbl  = r.collateral != null ? `$${r.collateral.toFixed(0)}` : '—';
    const premLbl  = r.net_premium != null
      ? `$${(r.net_premium * 100).toFixed(0)}<span class="ps-per-contract"> /contract</span>`
      : '—';
    const deltaLbl = r.delta  != null ? r.delta.toFixed(3) : '—';
    const ivLbl    = r.iv     != null ? r.iv.toFixed(1) + '%' : '—';
    const otmLbl   = r.otm_pct != null ? r.otm_pct.toFixed(1) + '%' : '—';

    const roiLbl  = r.roi_pct        != null ? r.roi_pct.toFixed(1) + '%' : '—';
    const aroiLbl = r.annualised_roi  != null ? r.annualised_roi.toFixed(1) + '%' : '—';
    const aroiCls = `ps-roi-cell ps-roi-${r.tier || 'good'}`;

    // News risk
    let riskHtml = '';
    if (r.news_risk === 'high') {
      riskHtml = `<span class="ps-risk ps-risk-high" title="${r.news_flag || 'High-risk event'}">🚨</span>`;
    } else if (r.news_risk === 'medium') {
      riskHtml = `<span class="ps-risk ps-risk-med" title="${r.news_flag || 'Moderate news'}">⚠️</span>`;
    } else {
      riskHtml = `<span class="ps-risk ps-risk-low" title="No significant news">✓</span>`;
    }

    return `<tr class="ss-row${r.news_risk === 'high' ? ' ps-row-high-risk' : ''}">
      <td><span class="${tierCls}">${tierIcon} ${tierLbl}</span></td>
      <td class="sym-col">
        <span class="ss-ticker ps-ticker-link"
              onclick="window.stockScreen.openModal('${r.symbol}')"
              title="View ${r.symbol} detail">${r.symbol}</span>
        <button class="grade-btn ${gradeCls}" style="margin-left:4px"
                onclick="window.stockScreen.openModal('${r.symbol}')"
                title="Graham Grade: ${r.grade || '?'}">${r.grade || '?'}</button>
      </td>
      <td class="ss-name-col">${r.company_name || ''}</td>
      <td class="num-col">${price}</td>
      <td class="num-col">${expLbl}</td>
      <td class="num-col">${r.dte != null ? r.dte + 'd' : '—'}</td>
      <td class="num-col ps-spread-col">${spreadLbl}</td>
      <td class="num-col">${collLbl}</td>
      <td class="num-col">${premLbl}</td>
      <td class="num-col">${deltaLbl}</td>
      <td class="num-col">${ivLbl}</td>
      <td class="num-col">${otmLbl}</td>
      <td class="num-col">${roiLbl}</td>
      <td class="num-col ${aroiCls}">${aroiLbl}</td>
      <td class="num-col">${riskHtml}</td>
    </tr>`;
  }

  _renderPagination() {
    const maxPage = Math.ceil(this._total / this._perPage) || 1;
    ['psPaginationTop', 'psPaginationBottom'].forEach(id => {
      const el = document.getElementById(id);
      if (!el) return;
      el.innerHTML = maxPage <= 1 ? '' : this._buildPaginationHTML(this._page, maxPage);
    });
  }

  _buildPaginationHTML(current, maxPage) {
    const pages = [];
    const add = (label, page, disabled, active) =>
      `<button class="ss-page-btn${active ? ' active' : ''}"
               ${disabled ? 'disabled' : ''}
               onclick="window.putScreen.goToPage(${page})">${label}</button>`;

    pages.push(add('«', 1, current === 1, false));
    pages.push(add('‹', current - 1, current === 1, false));

    const lo = Math.max(1,       current - 2);
    const hi = Math.min(maxPage, current + 2);
    if (lo > 1)       { pages.push(add('1', 1, false, false)); if (lo > 2) pages.push('<span class="ss-ellipsis">…</span>'); }
    for (let i = lo; i <= hi; i++) pages.push(add(i, i, false, i === current));
    if (hi < maxPage) { if (hi < maxPage - 1) pages.push('<span class="ss-ellipsis">…</span>'); pages.push(add(maxPage, maxPage, false, false)); }

    pages.push(add('›', current + 1, current === maxPage, false));
    pages.push(add('»', maxPage,     current === maxPage, false));
    return pages.join('');
  }

  _updateResultCount() {
    const el = document.getElementById('psResultCount');
    if (!el) return;
    if (this._total === 0) {
      el.textContent = 'No results';
    } else {
      const start = (this._page - 1) * this._perPage + 1;
      const end   = Math.min(this._page * this._perPage, this._total);
      el.textContent =
        `Showing ${start.toLocaleString()}–${end.toLocaleString()} of ${this._total.toLocaleString()} opportunities`;
    }
  }

  // ── Private: chip sync ───────────────────────────────────────────

  _syncChips(attrName, activeValue) {
    const attr = `data-${attrName}`;
    const val  = String(activeValue ?? '');
    document.querySelectorAll(`.ss-chip[${attr}]`).forEach(chip => {
      chip.classList.toggle('ss-chip-active', chip.getAttribute(attr) === val);
    });
  }

  // ── Private: sort arrow ──────────────────────────────────────────

  _updateSortArrows() {
    document.querySelectorAll('#psTable .ss-th-sort').forEach(th => {
      const col   = th.getAttribute('data-col');
      const arrow = th.querySelector('.sort-arrow');
      if (!arrow) return;
      if (col === this._sortCol) {
        arrow.textContent = this._sortDir === 'desc' ? ' ▼' : ' ▲';
      } else {
        arrow.textContent = '';
      }
    });
  }

  // ── Private: scan progress polling ──────────────────────────────

  _startProgressPoll() {
    if (this._pollInterval) clearInterval(this._pollInterval);
    this._pollInterval = setInterval(() => this._pollScanStatus(), 3000);
  }

  _pollScanStatus() {
    fetch('/api/put-screen/scan/status')
      .then(r => r.json())
      .then(p => this._renderScanProgress(p))
      .catch(() => {});
  }

  _renderScanProgress(p) {
    const wrap    = document.getElementById('psScanProgress');
    const bar     = document.getElementById('psScanBar');
    const text    = document.getElementById('psScanProgressText');
    const status  = document.getElementById('psScanStatus');
    const scanBtn = document.getElementById('psScanBtn');
    const stopBtn = document.getElementById('psStopBtn');

    if (p.running) {
      if (wrap) wrap.classList.remove('hidden');
      if (bar) {
        const pct = p.total > 0 ? Math.round(p.done / p.total * 100) : 0;
        bar.style.width = pct + '%';
        if (text) text.textContent =
          `${p.done.toLocaleString()} / ${p.total.toLocaleString()} (${pct}%)`
          + `  ·  ${p.current}`
          + (p.found > 0 ? `  ·  ${p.found} found` : '');
      }
      if (status) { status.className = 'ss-scan-status ss-scan-running'; status.textContent = '⚡ Scanning…'; }
      if (scanBtn) { scanBtn.disabled = true; scanBtn.textContent = '⏳ Scanning…'; }
      if (stopBtn) stopBtn.style.display = 'inline-block';
    } else {
      if (wrap) wrap.classList.add('hidden');
      if (status) status.className = 'ss-scan-status hidden';
      if (scanBtn) { scanBtn.disabled = false; scanBtn.textContent = '⚡ Scan Opportunities'; }
      if (stopBtn) stopBtn.style.display = 'none';

      if (p.finished_at && !this._lastFinish) {
        this.loadStats();
        this.load();
      }
      this._lastFinish = p.finished_at;
    }
  }
}
