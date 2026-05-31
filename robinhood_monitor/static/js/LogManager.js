/**
 * LogManager
 * Fetches and renders the Logs tab: alert history table and cash snapshot
 * history table. Also handles manual snapshot creation.
 * Depends on: app.pos.statusBadge(), fmtTime(), fmtMoney()
 */
class LogManager {
  /** @param {MonitorApp} app */
  constructor(app) {
    this.app = app;
  }

  // ── Public API ───────────────────────────────────────────────────

  /** Fetches alert history and renders the alerts table. */
  loadAlerts() {
    fetch('/api/alerts')
      .then(r => r.json())
      .then(alerts => {
        const tbody = document.getElementById('alertsBody');
        if (!alerts.length) {
          tbody.innerHTML = '<tr><td colspan="7" class="empty-msg">No alerts recorded yet</td></tr>';
          return;
        }
        tbody.innerHTML = alerts.map(a => this._buildAlertRow(a)).join('');
      })
      .catch(e => console.error('LogManager.loadAlerts error:', e));
  }

  /** Fetches cash snapshots and renders the cash history table. */
  loadCashHistory() {
    fetch('/api/cash')
      .then(r => r.json())
      .then(data => {
        const snaps = data.snapshots || [];
        const tbody = document.getElementById('cashBody');
        if (!snaps.length) {
          tbody.innerHTML = '<tr><td colspan="6" class="empty-msg">No snapshots recorded yet</td></tr>';
          return;
        }
        tbody.innerHTML = snaps.slice(0, 120).map(s => this._buildSnapshotRow(s)).join('');
      })
      .catch(e => console.error('LogManager.loadCashHistory error:', e));
  }

  /** POSTs a manual cash snapshot and refreshes the cash history table. */
  takeManualSnapshot() {
    fetch('/api/cash/snapshot', { method: 'POST' })
      .then(r => r.json())
      .then(res => { if (res.success) this.loadCashHistory(); })
      .catch(e => console.error('LogManager.takeManualSnapshot error:', e));
  }

  // ── Private row builders ─────────────────────────────────────────

  _buildAlertRow(a) {
    const price = a.current_price != null
      ? '$' + parseFloat(a.current_price).toFixed(2) : '--';
    const dist  = a.distance_pct  != null
      ? parseFloat(a.distance_pct).toFixed(1) + '%' : '--';
    const dte   = a.dte != null ? a.dte + 'd' : '--';

    return `<tr>
      <td style="white-space:nowrap">${fmtTime(a.created_at)}</td>
      <td class="sym-col">${a.symbol}</td>
      <td>${this.app.pos.statusBadge(a.status)}</td>
      <td class="msg-col">${a.message || ''}</td>
      <td class="num-col">${price}</td>
      <td class="num-col">${dist}</td>
      <td class="num-col">${dte}</td>
    </tr>`;
  }

  _buildSnapshotRow(s) {
    const fmt = v => (v != null ? fmtMoney(v) : '--');
    return `<tr>
      <td style="white-space:nowrap">${fmtTime(s.recorded_at)}</td>
      <td><span class="snap-type snap-${s.snapshot_type}">${s.snapshot_type}</span></td>
      <td class="num-col">${fmt(s.cash_available_for_withdrawal)}</td>
      <td class="num-col">${fmt(s.buying_power)}</td>
      <td class="num-col">${fmt(s.cash)}</td>
      <td class="num-col">${fmt(s.portfolio_equity)}</td>
    </tr>`;
  }
}
