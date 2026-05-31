/**
 * GradeManager
 * Handles Benjamin Graham stock grading — fetches data from /api/grade/:symbol,
 * manages an in-memory cache, renders the grade button in the positions table,
 * and controls the sliding sidebar panel.
 */
class GradeManager {
  constructor() {
    /** @type {Object.<string, Object>} symbol → grade data (or {_loading:true}) */
    this._cache = {};
  }

  // ── Colour helpers ──────────────────────────────────────────────

  /** Returns the CSS class name for a letter grade A–F. */
  gradeColor(g) {
    const map = { A: 'grade-A', B: 'grade-B', C: 'grade-C', D: 'grade-D', F: 'grade-F' };
    return map[g] || 'grade-err';
  }

  /** Returns the CSS colour variable for a 0–5 score bar. */
  gradeBarColor(score) {
    if (score >= 4) return 'var(--green)';
    if (score >= 3) return '#39d353';
    if (score >= 2) return 'var(--yellow)';
    if (score >= 1) return 'var(--orange)';
    return 'var(--red)';
  }

  // ── Button ──────────────────────────────────────────────────────

  /**
   * Returns an HTML string for the grade button.
   * Shows the cached grade if available, otherwise a loading placeholder.
   * @param {string} symbol
   * @returns {string} HTML
   */
  gradeBtn(symbol) {
    const cached = this._cache[symbol];
    if (cached && !cached._loading && cached.grade && !cached.error) {
      const g = cached.grade;
      return `<button class="grade-btn ${this.gradeColor(g)}"
                      onclick="window.openGradeSidebar('${symbol}')"
                      title="Graham Grade: ${g}">${g}</button>`;
    }
    return `<button class="grade-btn grade-loading"
                    id="grade-btn-${symbol}"
                    onclick="window.openGradeSidebar('${symbol}')"
                    title="Loading…">…</button>`;
  }

  // ── Data fetching ────────────────────────────────────────────────

  /**
   * Fetches the grade for a symbol in the background.
   * No-ops if the cache already has a non-loading entry.
   * @param {string} symbol
   */
  fetchGrade(symbol) {
    if (this._cache[symbol] && !this._cache[symbol]._loading) return;
    this._cache[symbol] = { _loading: true };

    fetch(`/api/grade/${symbol}`)
      .then(r => r.json())
      .then(data => {
        this._cache[symbol] = data;
        this._updateButtonInPlace(symbol, data);
      })
      .catch(() => {
        this._cache[symbol] = { error: 'Network error' };
      });
  }

  /**
   * Updates an existing grade button element without re-rendering the whole table.
   * @param {string} symbol
   * @param {Object} data
   */
  _updateButtonInPlace(symbol, data) {
    const btn = document.getElementById(`grade-btn-${symbol}`);
    if (btn && data.grade && !data.error) {
      btn.className   = `grade-btn ${this.gradeColor(data.grade)}`;
      btn.textContent = data.grade;
      btn.title       = `Graham Grade: ${data.grade}`;
      btn.removeAttribute('id');
    }
  }

  // ── Sidebar ──────────────────────────────────────────────────────

  /** Opens the sidebar for the given symbol. Fetches if not yet cached. */
  openSidebar(symbol) {
    const data = this._cache[symbol] || {};
    document.getElementById('gradeSidebar').classList.add('open');
    document.getElementById('gsOverlay').classList.add('open');
    this.renderSidebar(symbol, data);
    if (!data || data._loading || data.error) this.fetchGrade(symbol);
  }

  /** Closes the sidebar panel. */
  closeSidebar() {
    document.getElementById('gradeSidebar').classList.remove('open');
    document.getElementById('gsOverlay').classList.remove('open');
  }

  /**
   * Renders the sidebar content for the given symbol and data.
   * @param {string} symbol
   * @param {Object} data
   */
  renderSidebar(symbol, data) {
    document.getElementById('gsSymbolTitle').textContent = symbol;
    document.getElementById('gsNameTitle').textContent   = data.name || '';

    const gradeEl = document.getElementById('gsGradeBig');
    if (data._loading) {
      gradeEl.className   = 'gs-grade-big grade-loading';
      gradeEl.textContent = '…';
    } else if (data.error) {
      gradeEl.className   = 'gs-grade-big grade-err';
      gradeEl.textContent = '!';
    } else {
      gradeEl.className   = `gs-grade-big ${this.gradeColor(data.grade)}`;
      gradeEl.textContent = data.grade || '?';
    }

    const body = document.getElementById('gsSidebarBody');
    if (data._loading) {
      body.innerHTML = '<p style="color:var(--muted);text-align:center;padding:40px 0;">Loading data…</p>';
      return;
    }
    if (data.error) {
      body.innerHTML = `<p class="gs-error">⚠ ${data.error}</p>`;
      return;
    }

    body.innerHTML = this._buildSidebarBody(symbol, data);
  }

  /**
   * Busts the cache for a symbol and re-fetches, then re-renders sidebar and table.
   * @param {string} symbol
   * @param {Function} onComplete - callback(data) after refresh completes
   */
  refreshGrade(symbol, onComplete) {
    delete this._cache[symbol];
    this._cache[symbol] = { _loading: true };
    this.renderSidebar(symbol, this._cache[symbol]);

    fetch(`/api/grade/${symbol}/refresh`, { method: 'POST' })
      .then(r => r.json())
      .then(data => {
        this._cache[symbol] = data;
        this.renderSidebar(symbol, data);
        if (typeof onComplete === 'function') onComplete(data);
      });
  }

  // ── Private HTML builder ─────────────────────────────────────────

  _buildSidebarBody(symbol, data) {
    const fmtD   = v  => (v  != null) ? `$${parseFloat(v).toFixed(2)}`  : '—';
    const fmtN   = v  => (v  != null) ? `${parseFloat(v).toFixed(2)}`   : '—';
    const fmtP   = v  => (v  != null) ? `${parseFloat(v).toFixed(1)}%`  : '—';
    const fmtBig = v  => {
      if (v == null) return '—';
      const n = parseFloat(v);
      if (Math.abs(n) >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
      if (Math.abs(n) >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
      return `$${n.toLocaleString()}`;
    };

    const score  = parseFloat(data.score   || 0);
    const mos    = parseFloat(data.margin_of_safety ?? -999);
    const fcfVal = parseFloat(data.ttm_fcf || 0);

    const mosCls   = mos >= 30 ? 'gs-pos' : mos >= 0 ? 'gs-warn' : 'gs-neg';
    const fcfCls   = fcfVal > 0 ? 'gs-pos' : 'gs-neg';
    const priceCls = (data.intrinsic_value && data.current_price < data.intrinsic_value)
                     ? 'gs-pos' : 'gs-warn';

    const peOk  = data.pe_ratio && data.pe_ratio <= 15;
    const peWarn= data.pe_ratio && data.pe_ratio <= 25;
    const pbOk  = data.pb_ratio && data.pb_ratio <= 1.5;
    const pbWarn= data.pb_ratio && data.pb_ratio <= 3;
    const pepb  = data.pe_ratio && data.pb_ratio && (data.pe_ratio * data.pb_ratio) < 22.5;

    return `
      <div class="gs-score-bar">
        <div>
          <div class="gs-score-label">Graham Score</div>
          <div class="gs-score-val" style="color:${this.gradeBarColor(score)}">${score} / 5</div>
        </div>
        <div class="gs-bar-wrap">
          <div class="gs-bar-fill"
               style="width:${score / 5 * 100}%;background:${this.gradeBarColor(score)}"></div>
        </div>
      </div>

      <div class="gs-section">
        <div class="gs-section-title">Valuation</div>
        <div class="gs-row"><span class="gs-key">Current Price</span>     <span class="gs-val gs-neu">${fmtD(data.current_price)}</span></div>
        <div class="gs-row"><span class="gs-key">Intrinsic Value</span>   <span class="gs-val ${priceCls}">${fmtD(data.intrinsic_value)}</span></div>
        <div class="gs-row"><span class="gs-key">Margin of Safety</span>  <span class="gs-val ${mosCls}">${fmtP(data.margin_of_safety)}</span></div>
        <div class="gs-row"><span class="gs-key">52-Week High</span>      <span class="gs-val gs-neu">${fmtD(data.ath_52w)}</span></div>
        <div class="gs-row"><span class="gs-key">% of 52W High</span>     <span class="gs-val ${data.pct_of_ath < 80 ? 'gs-warn' : 'gs-neu'}">${fmtP(data.pct_of_ath)}</span></div>
        <div class="gs-row"><span class="gs-key">52-Week Low</span>       <span class="gs-val gs-neu">${fmtD(data.low_52w)}</span></div>
      </div>

      <div class="gs-section">
        <div class="gs-section-title">Fundamentals</div>
        <div class="gs-row"><span class="gs-key">EPS (TTM)</span>         <span class="gs-val ${data.eps_ttm > 0 ? 'gs-pos' : 'gs-neg'}">${fmtD(data.eps_ttm)}</span></div>
        <div class="gs-row"><span class="gs-key">Book Value / Share</span><span class="gs-val gs-neu">${fmtD(data.bvps)}</span></div>
        <div class="gs-row"><span class="gs-key">P/E Ratio (TTM)</span>  <span class="gs-val ${peOk ? 'gs-pos' : peWarn ? 'gs-warn' : 'gs-neg'}">${fmtN(data.pe_ratio)}×</span></div>
        <div class="gs-row"><span class="gs-key">P/B Ratio</span>         <span class="gs-val ${pbOk ? 'gs-pos' : pbWarn ? 'gs-warn' : 'gs-neg'}">${fmtN(data.pb_ratio)}×</span></div>
      </div>

      <div class="gs-section">
        <div class="gs-section-title">Cash Flow (TTM)</div>
        <div class="gs-row"><span class="gs-key">Free Cash Flow</span>    <span class="gs-val ${fcfCls}">${fmtBig(fcfVal)}</span></div>
        <div class="gs-row"><span class="gs-key">FCF / Share</span>       <span class="gs-val ${data.fcf_per_share > 0 ? 'gs-pos' : 'gs-neg'}">${fmtD(data.fcf_per_share)}</span></div>
      </div>

      <div class="gs-section">
        <div class="gs-section-title">Graham Criteria</div>
        <div class="gs-row"><span class="gs-key">P/E ≤ 15</span>           <span class="gs-val">${peOk ? '✅' : peWarn ? '🟡' : '❌'}</span></div>
        <div class="gs-row"><span class="gs-key">P/B ≤ 1.5</span>          <span class="gs-val">${pbOk ? '✅' : pbWarn ? '🟡' : '❌'}</span></div>
        <div class="gs-row"><span class="gs-key">MoS ≥ 30%</span>          <span class="gs-val">${mos >= 30 ? '✅' : mos >= 0 ? '🟡' : '❌'}</span></div>
        <div class="gs-row"><span class="gs-key">Positive FCF</span>       <span class="gs-val">${fcfVal > 0 ? '✅' : '❌'}</span></div>
        <div class="gs-row"><span class="gs-key">P/E × P/B &lt; 22.5</span><span class="gs-val">${pepb ? '✅' : '❌'}</span></div>
      </div>

      <button class="gs-refresh" onclick="window.refreshGrade('${symbol}')">↻ Refresh Data</button>
      <div class="gs-cached">Cached ${data.cached_at || ''} · Graham Number = √(22.5 × EPS × BVPS)</div>
    `;
  }
}
