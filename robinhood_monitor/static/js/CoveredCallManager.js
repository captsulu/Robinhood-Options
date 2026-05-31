/**
 * CoveredCallManager
 * Covered Call Finder tab.
 *
 * Key behaviours:
 *  - Fetches all matching rows from the API in one call (up to 2000)
 *  - Deduplicates to ONE row per ticker (best Ann.ROI shown)
 *  - Clicking a ticker opens a popup with ALL options for that ticker,
 *    grouped by expiration date
 *  - "Exclude Owned" toggle: hides tickers already in the positions list
 *    or with an active covered-call contract
 *  - "Affordable" toggle: hides tickers where 100 shares > available cash
 *  - Strike > price and delta <= 20% enforced by screener; UI trusts this
 *
 * Depends on: app.grades, app.cash, fmtMoney(), fmtTime()
 */
class CoveredCallManager {
  /** @param {MonitorApp} app */
  constructor(app) {
    this.app = app;

    // ── Filter / sort state ──────────────────────────────────────
    this._grade      = '';
    this._criteria   = '';
    this._tier       = '';
    this._hideRisk   = false;
    this._hideOwned  = true;    // on by default
    this._affordOnly = false;

    this._sortCol    = 'annualised_roi';
    this._sortDir    = 'desc';
    this._page       = 1;
    this._perPage    = 25;      // deduplicated rows per page

    // ── Data ─────────────────────────────────────────────────────
    this._allRows    = [];      // raw rows from API
    this._grouped    = {};      // symbol → rows[] sorted by exp then aroi
    this._symbols    = [];      // filtered+sorted unique-symbol list
    this._ownedSet   = new Set();
    this._availCash  = null;    // buying power from /api/cash

    this._pollInterval = null;
    this._lastFinish   = null;
  }

  // ── Public API ───────────────────────────────────────────────────

  /** Called when the tab is first activated. */
  init() {
    this.loadStats();
    this._loadContext().then(() => this.load());
    this._startProgressPoll();
  }

  /** Reload stats bar only (called on subsequent tab visits). */
  loadStats() {
    fetch('/api/covered-calls/stats')
      .then(r => r.json())
      .then(s => {
        const el = document.getElementById('ccStatsLabel');
        if (!el) return;
        if (!s.total) { el.textContent = 'No opportunities scanned yet'; return; }
        const bt   = s.by_tier    || {};
        const bg   = s.by_grade   || {};
        const bc   = s.by_criteria || {};
        const icons  = { legendary: '🏆', epic: '⚡', rare: '💎', good: '✓' };
        const clbls  = { delta20: '20Δ', otm20: '20%OTM', cheap: '≤$10' };
        const tParts = ['legendary','epic','rare','good'].filter(t => bt[t]).map(t => `${icons[t]}${bt[t]}`);
        const gParts = ['A','B','C','D','F'].filter(g => bg[g]).map(g => `${g}:${bg[g]}`);
        const cParts = Object.entries(bc).map(([k,v]) => `${clbls[k]||k}:${v}`);
        const risk   = s.high_risk_count ? `  ·  🚨 ${s.high_risk_count} high-risk` : '';
        const when   = s.last_scan ? '  ·  Updated ' + fmtTime(s.last_scan) : '';
        el.textContent =
          `${s.total.toLocaleString()} opps  (${tParts.join('  ')})  ·  ` +
          `Grades: ${gParts.join(' ')}  ·  ${cParts.join(' ')}${risk}${when}`;
      })
      .catch(() => {});
  }

  /** Fetch all rows from API then re-process. */
  load() {
    const params = new URLSearchParams({
      sort:     'annualised_roi',
      dir:      'desc',
      page:     1,
      per_page: 2000,
    });
    if (this._grade)    params.set('grade',    this._grade);
    if (this._criteria) params.set('criteria', this._criteria);
    if (this._tier)     params.set('tier',     this._tier);
    if (this._hideRisk) params.set('news_risk','low');

    fetch(`/api/covered-calls?${params}`)
      .then(r => r.json())
      .then(data => {
        this._allRows = data.opportunities || [];
        this._process();
      })
      .catch(e => console.error('CoveredCallManager.load:', e));
  }

  // ── Filters ──────────────────────────────────────────────────────

  setGrade(g)    { this._grade    = g; this._page = 1; this._syncChips('cc-grade', g); this.load(); }
  setCriteria(c) { this._criteria = c; this._page = 1; this._syncChips('cc-crit',  c); this.load(); }
  setTier(t)     { this._tier     = t; this._page = 1; this._syncChips('cc-tier',  t); this.load(); }

  toggleHideRisk() {
    this._hideRisk = !this._hideRisk;
    this._page = 1;
    document.getElementById('ccHideRiskBtn')?.classList.toggle('ss-preset-active', this._hideRisk);
    this.load();
  }

  toggleHideOwned() {
    this._hideOwned = !this._hideOwned;
    this._page = 1;
    document.getElementById('ccHideOwnedBtn')?.classList.toggle('ss-preset-active', this._hideOwned);
    this._process();
  }

  toggleAffordOnly() {
    this._affordOnly = !this._affordOnly;
    this._page = 1;
    document.getElementById('ccAffordBtn')?.classList.toggle('ss-preset-active', this._affordOnly);
    this._process();
  }

  // ── Sort / pagination ────────────────────────────────────────────

  setSort(col) {
    if (this._sortCol === col) {
      this._sortDir = this._sortDir === 'desc' ? 'asc' : 'desc';
    } else {
      this._sortCol = col; this._sortDir = 'desc';
    }
    this._page = 1;
    this._process();
  }

  goToPage(p) {
    const max = Math.ceil(this._symbols.length / this._perPage) || 1;
    this._page = Math.max(1, Math.min(p, max));
    this._renderPage();
  }

  // ── Scan control ─────────────────────────────────────────────────

  triggerScan(btn) {
    if (btn) { btn.disabled = true; btn.textContent = '⏳ Starting…'; }
    const stopBtn = document.getElementById('ccStopBtn');
    if (stopBtn) stopBtn.style.display = 'inline-block';
    fetch('/api/covered-calls/scan', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ grades: ['A', 'B'] }),
    })
      .then(r => r.json())
      .then(data => {
        if (!data.success) {
          alert(data.message || 'Could not start scan');
          if (btn) { btn.disabled = false; btn.textContent = '📞 Scan Opportunities'; }
          if (stopBtn) stopBtn.style.display = 'none';
        }
        this._startProgressPoll();
      })
      .catch(() => {
        if (btn) { btn.disabled = false; btn.textContent = '📞 Scan Opportunities'; }
        if (stopBtn) stopBtn.style.display = 'none';
      });
  }

  stopScan() {
    fetch('/api/covered-calls/scan/stop', { method: 'POST' });
    document.getElementById('ccStopBtn')?.style && (document.getElementById('ccStopBtn').style.display = 'none');
  }

  // ── Popup ────────────────────────────────────────────────────────

  /** Open the per-ticker options popup. */
  openPopup(symbol) {
    const rows = this._grouped[symbol];
    if (!rows || !rows.length) return;

    const r0    = rows[0];
    const price = r0.current_price != null ? fmtMoney(r0.current_price) : '—';
    const cost  = r0.current_price != null ? fmtMoney(r0.current_price * 100) : '—';

    // ── Header info ───────────────────────────────────────────────
    const canAfford = this._availCash !== null && r0.current_price * 100 <= this._availCash;
    const affordTxt = this._availCash !== null
      ? `<span style="font-size:12px;margin-left:10px;${canAfford ? 'color:var(--green)' : 'color:var(--red)'}">` +
        `${canAfford ? '✓ Affordable' : '✗ Over budget'} — ${cost} for 100 shares</span>`
      : `<span style="font-size:12px;color:var(--muted);margin-left:10px">${cost} for 100 shares</span>`;
    const ownedTxt = this._ownedSet.has(symbol)
      ? '<span style="color:var(--orange);font-size:12px;margin-left:10px">⚠ Already in portfolio</span>'
      : '';

    document.getElementById('ccPopupTitle').innerHTML =
      `<span style="font-size:18px;font-weight:700">${symbol}</span>` +
      `<span style="color:var(--muted);font-size:14px;margin-left:8px">— ${r0.company_name || ''}</span>` +
      `<span style="color:var(--muted);font-size:13px;margin-left:10px">${price}/share</span>` +
      affordTxt + ownedTxt;

    document.getElementById('ccPopupGrade').innerHTML =
      `<button class="grade-btn ${this.app.grades.gradeColor(r0.grade)}" ` +
      `onclick="window.stockScreen.openModal('${symbol}')" title="Graham Grade: ${r0.grade||'?'}">${r0.grade||'?'}</button>`;

    // ── Build table grouped by expiration ─────────────────────────
    const byExp = {};
    rows.forEach(r => {
      if (!byExp[r.expiration]) byExp[r.expiration] = [];
      byExp[r.expiration].push(r);
    });
    // Sort within each expiration by ann.roi desc
    Object.values(byExp).forEach(arr => arr.sort((a, b) => (b.annualised_roi || 0) - (a.annualised_roi || 0)));

    const critMap  = { delta20: '20Δ', otm20: '20%OTM', cheap: '≤$10' };
    const tierIcon = { legendary: '🏆', epic: '⚡', rare: '💎', good: '✓', other: '·' };

    let html = '';
    Object.keys(byExp).sort().forEach(exp => {
      const expRows = byExp[exp];
      const expLabel = new Date(exp + 'T12:00:00').toLocaleDateString('en-US',
        { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' });

      html += `<tr>
        <td colspan="9" style="padding:6px 12px;font-weight:700;font-size:12px;
            color:var(--blue);background:rgba(88,166,255,.08);
            letter-spacing:.04em;border-bottom:1px solid var(--border);">
          📅 ${expLabel} &nbsp;·&nbsp; ${expRows[0].dte}d to expiry &nbsp;·&nbsp; ${expRows.length} strike${expRows.length !== 1 ? 's' : ''}
        </td></tr>`;

      expRows.forEach(r => {
        const strikeLbl = r.strike != null ? `$${r.strike.toFixed(2)}` : '—';
        const otmLbl    = r.otm_pct != null ? r.otm_pct.toFixed(1) + '%' : '—';
        const premSh    = r.premium_per_share != null ? `$${r.premium_per_share.toFixed(2)}` : '—';
        const prem100   = r.premium_per_share != null ? fmtMoney(r.premium_per_share * 100) : '—';
        const deltaLbl  = r.delta != null ? r.delta.toFixed(3) : '—';
        const ivLbl     = r.iv    != null ? r.iv.toFixed(1) + '%' : '—';
        const aroiLbl   = r.annualised_roi != null ? r.annualised_roi.toFixed(1) + '%' : '—';
        const aroiCls   = `ps-roi-cell ps-roi-${r.tier || 'good'}`;
        const tIcon     = tierIcon[r.tier] || '·';
        const crit      = critMap[r.criteria] || r.criteria || '—';

        html += `<tr class="cc-popup-row">
          <td class="num-col" style="font-weight:600">${strikeLbl}</td>
          <td class="num-col">${otmLbl}</td>
          <td class="num-col">${premSh}<span class="ps-per-contract">/sh</span></td>
          <td class="num-col" style="color:var(--green)">${prem100}<span class="ps-per-contract">/contract</span></td>
          <td class="num-col">${deltaLbl}</td>
          <td class="num-col">${ivLbl}</td>
          <td class="num-col ${aroiCls}">${aroiLbl}</td>
          <td><span class="ps-tier-badge ps-tier-${r.tier||'good'}">${tIcon}</span></td>
          <td><span style="font-size:11px;color:var(--muted)">${crit}</span></td>
        </tr>`;
      });
    });

    document.getElementById('ccPopupBody').innerHTML = html;
    document.getElementById('ccPopupOverlay').classList.remove('hidden');
    document.getElementById('ccPopup').classList.remove('hidden');
  }

  closePopup() {
    document.getElementById('ccPopup').classList.add('hidden');
    document.getElementById('ccPopupOverlay').classList.add('hidden');
  }

  // ── Private: data processing ─────────────────────────────────────

  /** Group, filter, sort, then render. */
  _process() {
    // Group by symbol; sort each group by expiration then aroi desc
    const grouped = {};
    this._allRows.forEach(r => {
      if (!grouped[r.symbol]) grouped[r.symbol] = [];
      grouped[r.symbol].push(r);
    });
    Object.values(grouped).forEach(arr =>
      arr.sort((a, b) => {
        if (a.expiration !== b.expiration) return a.expiration < b.expiration ? -1 : 1;
        return (b.annualised_roi || 0) - (a.annualised_roi || 0);
      })
    );
    this._grouped = grouped;

    // Build list of { symbol, best } with filters applied
    let list = Object.keys(grouped).map(sym => {
      const best = grouped[sym].reduce((a, b) =>
        (b.annualised_roi || 0) > (a.annualised_roi || 0) ? b : a
      );
      return { symbol: sym, best };
    });

    if (this._hideOwned) {
      list = list.filter(s => !this._ownedSet.has(s.symbol));
    }
    if (this._affordOnly && this._availCash !== null) {
      list = list.filter(s => (s.best.current_price || 0) * 100 <= this._availCash);
    }

    // Sort
    list.sort((a, b) => {
      const av = a.best[this._sortCol] ?? (this._sortDir === 'desc' ? -Infinity : Infinity);
      const bv = b.best[this._sortCol] ?? (this._sortDir === 'desc' ? -Infinity : Infinity);
      if (bv > av) return this._sortDir === 'desc' ?  1 : -1;
      if (bv < av) return this._sortDir === 'desc' ? -1 :  1;
      return 0;
    });

    this._symbols = list;
    const max = Math.ceil(list.length / this._perPage) || 1;
    if (this._page > max) this._page = max;
    this._renderPage();
  }

  _renderPage() {
    const total = this._symbols.length;
    const start = (this._page - 1) * this._perPage;
    const page  = this._symbols.slice(start, start + this._perPage);
    this._renderTable(page, total);
    this._renderPagination(total);
    this._updateResultCount(total, start, Math.min(start + this._perPage, total));
  }

  // ── Private: rendering ───────────────────────────────────────────

  _renderTable(page, total) {
    const tbody = document.getElementById('ccBody');
    if (!page.length) {
      tbody.innerHTML = '<tr><td colspan="14" class="empty-msg">' +
        (this._allRows.length === 0
          ? 'No opportunities found — run a scan first.'
          : 'No opportunities match the current filters.') +
        '</td></tr>';
      return;
    }
    // Seed stock screen cache
    if (window.stockScreen) {
      page.forEach(({ symbol, best: r }) => {
        if (!window.stockScreen._stockData[symbol]) {
          window.stockScreen._stockData[symbol] = {
            company_name: r.company_name, grade: r.grade,
            current_price: r.current_price, _partial: true,
          };
        }
      });
    }
    tbody.innerHTML = page.map(({ symbol, best }) =>
      this._buildRow(symbol, best, this._grouped[symbol].length)
    ).join('');
    this._updateSortArrows();
  }

  _buildRow(symbol, r, optCount) {
    const tierCls  = `ps-tier-badge ps-tier-${r.tier || 'good'}`;
    const tierIcon = { legendary: '🏆', epic: '⚡', rare: '💎', good: '✓', other: '·' };
    const tierLbl  = r.tier ? r.tier.charAt(0).toUpperCase() + r.tier.slice(1) : '—';
    const gradeCls = this.app.grades.gradeColor(r.grade);

    const price   = r.current_price != null ? fmtMoney(r.current_price) : '—';
    const cost100 = r.current_price != null ? fmtMoney(r.current_price * 100) : '—';

    const canAfford = this._availCash !== null && (r.current_price || 0) * 100 <= this._availCash;
    const affordBadge = this._availCash !== null
      ? `<div style="font-size:10px;margin-top:2px;${canAfford ? 'color:var(--green)' : 'color:var(--red)'}">` +
        `${canAfford ? '✓ affordable' : '✗ over budget'}</div>`
      : '';

    const expLbl = r.expiration
      ? new Date(r.expiration + 'T12:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
      : '—';

    const strikeLbl = r.strike != null ? `$${r.strike.toFixed(2)}` : '—';
    const otmLbl    = r.otm_pct != null ? r.otm_pct.toFixed(1) + '%' : '—';
    const premLbl   = r.premium_per_share != null ? `$${r.premium_per_share.toFixed(2)}` : '—';
    const deltaLbl  = r.delta != null ? r.delta.toFixed(3) : '—';
    const aroiLbl   = r.annualised_roi != null ? r.annualised_roi.toFixed(1) + '%' : '—';
    const aroiCls   = `ps-roi-cell ps-roi-${r.tier || 'good'}`;

    const ownedBadge = this._ownedSet.has(symbol)
      ? '<div style="font-size:10px;color:var(--muted)">owned</div>' : '';

    let riskHtml;
    if (r.news_risk === 'high')
      riskHtml = `<span class="ps-risk ps-risk-high" title="${r.news_flag||'High-risk'}">🚨</span>`;
    else if (r.news_risk === 'medium')
      riskHtml = `<span class="ps-risk ps-risk-med"  title="${r.news_flag||'Moderate news'}">⚠️</span>`;
    else
      riskHtml = `<span class="ps-risk ps-risk-low">✓</span>`;

    const optBadge =
      `<span class="cc-opt-count" onclick="window.coveredCalls.openPopup('${symbol}')"
             title="View all ${optCount} option${optCount!==1?'s':''} for ${symbol}">` +
      `${optCount} option${optCount !== 1 ? 's' : ''} ›</span>`;

    return `<tr class="ss-row${r.news_risk === 'high' ? ' ps-row-high-risk' : ''}">
      <td><span class="${tierCls}">${tierIcon[r.tier]||'·'} ${tierLbl}</span></td>
      <td class="sym-col">
        <span class="ss-ticker ps-ticker-link"
              onclick="window.coveredCalls.openPopup('${symbol}')"
              title="View all options for ${symbol}">${symbol}</span>
        <button class="grade-btn ${gradeCls}" style="margin-left:4px"
                onclick="window.stockScreen.openModal('${symbol}')"
                title="Graham Grade: ${r.grade||'?'}">${r.grade||'?'}</button>
        ${ownedBadge}
      </td>
      <td class="ss-name-col">${r.company_name || ''}</td>
      <td class="num-col">${price}</td>
      <td class="num-col" style="font-size:12px">${cost100}${affordBadge}</td>
      <td class="num-col">${expLbl}</td>
      <td class="num-col">${r.dte != null ? r.dte + 'd' : '—'}</td>
      <td class="num-col">${strikeLbl}</td>
      <td class="num-col">${otmLbl}</td>
      <td class="num-col">${premLbl}</td>
      <td class="num-col">${deltaLbl}</td>
      <td class="num-col ${aroiCls}">${aroiLbl}</td>
      <td>${optBadge}</td>
      <td>${riskHtml}</td>
    </tr>`;
  }

  _renderPagination(total) {
    const maxPage = Math.ceil(total / this._perPage) || 1;
    ['ccPaginationTop','ccPaginationBottom'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.innerHTML = maxPage <= 1 ? '' : this._buildPagHTML(this._page, maxPage);
    });
  }

  _buildPagHTML(cur, max) {
    const btn = (lbl, pg, dis, act) =>
      `<button class="ss-page-btn${act?' active':''}" ${dis?'disabled':''} ` +
      `onclick="window.coveredCalls.goToPage(${pg})">${lbl}</button>`;
    const p = [];
    p.push(btn('«', 1, cur===1, false));
    p.push(btn('‹', cur-1, cur===1, false));
    const lo = Math.max(1, cur-2), hi = Math.min(max, cur+2);
    if (lo > 1) { p.push(btn('1',1,false,false)); if (lo>2) p.push('<span class="ss-ellipsis">…</span>'); }
    for (let i=lo; i<=hi; i++) p.push(btn(i, i, false, i===cur));
    if (hi < max) { if (hi<max-1) p.push('<span class="ss-ellipsis">…</span>'); p.push(btn(max,max,false,false)); }
    p.push(btn('›', cur+1, cur===max, false));
    p.push(btn('»', max, cur===max, false));
    return p.join('');
  }

  _updateResultCount(total, start, end) {
    const el = document.getElementById('ccResultCount');
    if (!el) return;
    if (total === 0) {
      el.textContent = 'No results';
    } else {
      el.textContent =
        `Showing ${(start+1).toLocaleString()}–${end.toLocaleString()} of ` +
        `${total.toLocaleString()} ticker${total!==1?'s':''} ` +
        `(${this._allRows.length.toLocaleString()} total options)`;
    }
  }

  // ── Private: context loader ──────────────────────────────────────

  async _loadContext() {
    try {
      const [posData, cashData] = await Promise.all([
        fetch('/api/positions').then(r => r.json()).catch(() => ({})),
        fetch('/api/cash').then(r => r.json()).catch(() => ({})),
      ]);
      // Mark every symbol that is in current positions (stocks + option contracts)
      this._ownedSet = new Set();
      (posData.positions || []).forEach(p => this._ownedSet.add(p.symbol));
      // Use buying power as the capital budget
      if (cashData.live) {
        this._availCash = parseFloat(cashData.live.buying_power || 0) || null;
      }
      // Update the affordable button label with cash amount
      const btn = document.getElementById('ccAffordBtn');
      if (btn && this._availCash !== null) {
        btn.title = `Only show stocks where 100 shares ≤ ${fmtMoney(this._availCash)} (your buying power)`;
      }
    } catch (e) {
      console.error('CoveredCallManager._loadContext:', e);
    }
  }

  // ── Private: chip sync + sort arrows ────────────────────────────

  _syncChips(attr, val) {
    const a = `data-${attr}`;
    document.querySelectorAll(`.ss-chip[${a}]`).forEach(c =>
      c.classList.toggle('ss-chip-active', c.getAttribute(a) === String(val ?? ''))
    );
  }

  _updateSortArrows() {
    document.querySelectorAll('#ccTable .ss-th-sort').forEach(th => {
      const col   = th.getAttribute('data-col');
      const arrow = th.querySelector('.sort-arrow');
      if (!arrow) return;
      arrow.textContent = col === this._sortCol
        ? (this._sortDir === 'desc' ? ' ▼' : ' ▲') : '';
    });
  }

  // ── Private: scan progress polling ──────────────────────────────

  _startProgressPoll() {
    if (this._pollInterval) clearInterval(this._pollInterval);
    this._pollInterval = setInterval(() => this._pollStatus(), 3000);
  }

  _pollStatus() {
    fetch('/api/covered-calls/scan/status')
      .then(r => r.json())
      .then(p => this._renderProgress(p))
      .catch(() => {});
  }

  _renderProgress(p) {
    const wrap    = document.getElementById('ccScanProgress');
    const bar     = document.getElementById('ccScanBar');
    const text    = document.getElementById('ccScanProgressText');
    const status  = document.getElementById('ccScanStatus');
    const scanBtn = document.getElementById('ccScanBtn');
    const stopBtn = document.getElementById('ccStopBtn');

    if (p.running) {
      wrap?.classList.remove('hidden');
      if (bar) {
        const pct = p.total > 0 ? Math.round(p.done / p.total * 100) : 0;
        bar.style.width = pct + '%';
        if (text) text.textContent =
          `${p.done.toLocaleString()} / ${p.total.toLocaleString()} (${pct}%)` +
          `  ·  ${p.current}` +
          (p.found > 0 ? `  ·  ${p.found} found` : '');
      }
      if (status) { status.className = 'ss-scan-status ss-scan-running'; status.textContent = '📞 Scanning…'; }
      if (scanBtn) { scanBtn.disabled = true; scanBtn.textContent = '⏳ Scanning…'; }
      if (stopBtn) stopBtn.style.display = 'inline-block';
    } else {
      wrap?.classList.add('hidden');
      if (status) status.className = 'ss-scan-status hidden';
      if (scanBtn) { scanBtn.disabled = false; scanBtn.textContent = '📞 Scan Opportunities'; }
      if (stopBtn) stopBtn.style.display = 'none';
      if (p.finished_at && p.finished_at !== this._lastFinish) {
        this.loadStats();
        this.load();
      }
      this._lastFinish = p.finished_at;
    }
  }
}
