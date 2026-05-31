/**
 * CashManager
 * Fetches and renders the Cash & Funds section including the margin toggle,
 * open/close comparison grid, and collateral tab card sync.
 * Depends on: app.lastTotalCollateral, fmtMoney()
 */
class CashManager {
  /** @param {MonitorApp} app */
  constructor(app) {
    this.app   = app;
    /** @type {Object|null} Last live cash data from /api/cash */
    this._live = null;
  }

  // ── Public API ───────────────────────────────────────────────────

  /** Returns the last fetched live cash object (may be null). */
  getLive() {
    return this._live;
  }

  /** Fetches live cash data and re-renders all cash-related elements. */
  refresh() {
    fetch('/api/cash')
      .then(r => r.json())
      .then(data => {
        if (data.live) {
          this._live = data.live;
          this._renderCards(data.live);
          this._syncCollateralTab(data.live);
          // Re-render capital P&L if a summary is cached
          if (this.app.transfers.getSummary()) {
            this.app.transfers.renderCapitalCards(this.app.transfers.getSummary());
          }
        }
        this._renderComparison(data.snapshots || []);
      });
  }

  /** Called when the "Include Margin" checkbox changes. */
  onMarginToggle() {
    const cb = document.getElementById('marginToggle');
    try { localStorage.setItem('bpMargin', cb.checked ? '1' : '0'); } catch (e) { /* storage may be unavailable */ }
    if (!this._live) return;
    const bp = cb.checked
      ? (this._live.buying_power_with_margin || this._live.buying_power)
      : this._live.buying_power;
    document.getElementById('cashBuyingPower').textContent = fmtMoney(bp);
    this._renderMarginHint(this._live, cb.checked);
  }

  // ── Private renderers ────────────────────────────────────────────

  _renderCards(live) {
    const useMargin = this._isMarginChecked();
    const bp = useMargin
      ? (live.buying_power_with_margin || live.buying_power)
      : live.buying_power;

    document.getElementById('cashWithdrawable').textContent  = fmtMoney(live.cash_available_for_withdrawal);
    document.getElementById('cashBuyingPower').textContent   = fmtMoney(bp);
    document.getElementById('cashTotalCard').textContent     = fmtMoney(live.cash);
    document.getElementById('cashHeld').textContent          = fmtMoney(live.cash_held_for_orders);
    document.getElementById('cashUncleared').textContent     = fmtMoney(live.uncleared_deposits);
    document.getElementById('cashEquity').textContent        = fmtMoney(live.portfolio_equity);
    this._renderMarginHint(live, useMargin);
  }

  _renderMarginHint(live, useMargin) {
    const bpCash = parseFloat(live.buying_power || 0);
    const bpMgn  = parseFloat(live.buying_power_with_margin || live.buying_power || 0);
    const same   = Math.abs(bpCash - bpMgn) < 0.01;

    const note = document.getElementById('marginNote');
    const alt  = document.getElementById('marginAlt');

    if (note) note.style.display = (useMargin && same) ? 'block' : 'none';
    if (alt) {
      if (!same) {
        alt.textContent   = useMargin ? `Cash: ${fmtMoney(bpCash)}` : `w/ Margin: ${fmtMoney(bpMgn)}`;
        alt.style.display = 'block';
      } else {
        alt.style.display = 'none';
      }
    }
  }

  _syncCollateralTab(live) {
    const locked = this.app.lastTotalCollateral || 0;
    const colWith = document.getElementById('colTabWithdrawable');
    const colCash = document.getElementById('colTabCash');
    const colFree = document.getElementById('colTabFree');

    if (colWith) colWith.textContent = fmtMoney(live.cash_available_for_withdrawal);
    if (colCash) colCash.textContent = fmtMoney(live.cash);
    if (colFree) {
      const free = parseFloat(live.cash || 0) - locked;
      colFree.textContent = fmtMoney(free);
      colFree.style.color = free >= 0 ? '' : 'var(--red)';
    }
  }

  _renderComparison(snapshots) {
    const today     = new Date().toISOString().slice(0, 10);
    const todaySnaps = snapshots.filter(s => s.recorded_at && s.recorded_at.startsWith(today));
    const openSnap   = todaySnaps.find(s => s.snapshot_type === 'open');
    const closeSnap  = todaySnaps.find(s => s.snapshot_type === 'close');
    const div        = document.getElementById('cashComparison');

    if (!openSnap && !closeSnap) {
      div.innerHTML = '<p class="hint" style="margin-top:10px">No open/close snapshots captured today yet.</p>';
      return;
    }

    const fmt   = v => (v != null) ? fmtMoney(v) : '--';
    const delta = (a, b) => {
      if (a == null || b == null) return '';
      const d   = parseFloat(b) - parseFloat(a);
      const cls = d >= 0 ? 'pos-delta' : 'neg-delta';
      return `<span class="${cls}">${d >= 0 ? '+' : ''}$${Math.abs(d).toFixed(2)}</span>`;
    };

    const o = openSnap  || {};
    const c = closeSnap || {};

    div.innerHTML = `
      <div class="comparison-grid">
        <div class="comp-header"></div>
        <div class="comp-header">🔔 Open</div>
        <div class="comp-header">🔕 Close</div>
        <div class="comp-header">Change</div>
        <div class="comp-label">Withdrawable</div>
        <div>${fmt(o.cash_available_for_withdrawal)}</div>
        <div>${fmt(c.cash_available_for_withdrawal)}</div>
        <div>${delta(o.cash_available_for_withdrawal, c.cash_available_for_withdrawal)}</div>
        <div class="comp-label">Buying Power</div>
        <div>${fmt(o.buying_power)}</div>
        <div>${fmt(c.buying_power)}</div>
        <div>${delta(o.buying_power, c.buying_power)}</div>
        <div class="comp-label">Portfolio</div>
        <div>${fmt(o.portfolio_equity)}</div>
        <div>${fmt(c.portfolio_equity)}</div>
        <div>${delta(o.portfolio_equity, c.portfolio_equity)}</div>
      </div>`;
  }

  _isMarginChecked() {
    const el = document.getElementById('marginToggle');
    return el ? el.checked : false;
  }
}
