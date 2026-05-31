/**
 * TransferManager
 * Fetches and renders the transfer history table and the Capital & Returns
 * summary cards. Also handles the "Mark Cleared" action.
 * Depends on: app.cash.getLive(), fmtDate(), fmtMoney()
 */
class TransferManager {
  /** @param {MonitorApp} app */
  constructor(app) {
    this.app      = app;
    /** @type {Object|null} Last fetched /api/transfers summary */
    this._summary = null;
  }

  // ── Public API ───────────────────────────────────────────────────

  /** Returns the last cached capital summary (consumed by CashManager). */
  getSummary() {
    return this._summary;
  }

  /** Fetches transfer list + capital summary and re-renders. */
  refresh() {
    fetch('/api/transfers')
      .then(r => r.json())
      .then(data => {
        this.renderCapitalCards(data.summary);
        this._renderTable(data.transfers);
      })
      .catch(e => console.error('TransferManager.refresh error:', e));
  }

  /**
   * Syncs bank transfers from Robinhood, then re-renders.
   * @param {HTMLElement|null} btn - The button element to show feedback on.
   */
  sync(btn) {
    if (btn) { btn.disabled = true; btn.textContent = '⏳ Syncing…'; }
    fetch('/api/transfers/sync', { method: 'POST' })
      .then(r => r.json())
      .then(data => {
        if (data.success) {
          this.renderCapitalCards(data.summary);
          this._renderTable(data.transfers);
        }
      })
      .catch(e => console.error('TransferManager.sync error:', e))
      .finally(() => {
        if (btn) { btn.disabled = false; btn.textContent = '↻ Sync from Robinhood'; }
      });
  }

  /**
   * Renders the Capital & Returns summary cards.
   * Uses live portfolio equity from CashManager if available.
   * @param {Object} s - capital summary from API
   */
  renderCapitalCards(s) {
    if (!s) return;
    this._summary = s;

    document.getElementById('capNetCapital').textContent = fmtMoney(s.net_capital);
    document.getElementById('capPending').textContent    = s.pending_deposits > 0
      ? fmtMoney(s.pending_deposits) : '$0.00';
    document.getElementById('capDepWith').textContent    =
      `Deposited ${fmtMoney(s.total_deposited)}` +
      (s.total_withdrawn > 0 ? ` / Withdrawn ${fmtMoney(s.total_withdrawn)}` : '');

    this._renderPnl(s);
  }

  /**
   * Marks a single transfer as cleared via API, then re-renders.
   * @param {number}          id  - transfer DB id
   * @param {HTMLElement|null} btn
   */
  markCleared(id, btn) {
    if (btn) { btn.disabled = true; btn.textContent = '…'; }
    fetch(`/api/transfers/${id}/clear`, { method: 'POST' })
      .then(r => r.json())
      .then(data => {
        if (data.success) {
          this.renderCapitalCards(data.summary);
          this._renderTable(data.transfers);
        }
      });
  }

  /**
   * Deletes a manually-entered transfer after confirmation, then re-renders.
   * @param {number}          id  - transfer DB id
   * @param {HTMLElement|null} btn
   */
  deleteTransfer(id, btn) {
    if (!confirm('Remove this manual transfer entry? This cannot be undone.')) return;
    if (btn) { btn.disabled = true; btn.textContent = '…'; }
    fetch(`/api/transfers/${id}`, { method: 'DELETE' })
      .then(r => r.json())
      .then(data => {
        if (data.success) {
          this.renderCapitalCards(data.summary);
          this._renderTable(data.transfers);
        } else {
          alert('Could not delete: ' + (data.message || 'unknown error'));
          if (btn) { btn.disabled = false; btn.textContent = '🗑'; }
        }
      })
      .catch(e => {
        console.error('deleteTransfer error:', e);
        if (btn) { btn.disabled = false; btn.textContent = '🗑'; }
      });
  }

  // ── Private renderers ────────────────────────────────────────────

  _renderPnl(s) {
    const live   = this.app.cash.getLive();
    const equity = live ? parseFloat(live.portfolio_equity || 0) : null;

    const eqEl   = document.getElementById('capEquity');
    const pnlEl  = document.getElementById('capPnl');
    const retEl  = document.getElementById('capReturn');
    const cardEl = document.getElementById('capPnlCard');

    if (equity !== null) {
      const pnl = equity - parseFloat(s.net_capital || 0);
      const ret = s.net_capital > 0 ? (pnl / s.net_capital * 100) : 0;

      eqEl.textContent  = fmtMoney(equity);
      pnlEl.textContent = (pnl >= 0 ? '+' : '') + fmtMoney(pnl);
      retEl.textContent = (ret >= 0 ? '+' : '') + ret.toFixed(2) + '%';

      pnlEl.className  = `card-value ${pnl > 0 ? 'pnl-pos' : pnl < 0 ? 'pnl-neg' : 'pnl-neutral'}`;
      retEl.className  = `card-value ${ret > 0 ? 'pnl-pos' : ret < 0 ? 'pnl-neg' : 'pnl-neutral'}`;
      cardEl.className = `card ${pnl > 0 ? 'card-pnl-pos' : pnl < 0 ? 'card-pnl-neg' : ''}`;
    } else {
      eqEl.textContent  = '(loading…)';
      pnlEl.textContent = '--';
      retEl.textContent = '--';
    }
  }

  _renderTable(transfers) {
    const tbody = document.getElementById('xferBody');
    if (!transfers || !transfers.length) {
      tbody.innerHTML = '<tr><td colspan="7" class="empty-msg">No transfers recorded</td></tr>';
      return;
    }
    tbody.innerHTML = transfers.map(t => this._buildTransferRow(t)).join('');
  }

  _buildTransferRow(t) {
    const dirCls   = t.direction === 'deposit' ? 'dir-deposit' : 'dir-withdrawal';
    const stCls    = `status-${t.status}`;
    const isManual = t.source === 'manual';
    const src      = isManual ? '✏ Manual' : '🤖 RH';

    const clearBtn = (t.status === 'pending')
      ? `<button class="clear-btn" onclick="window.markCleared(${t.id}, this)">✓ Mark Cleared</button>`
      : '';
    const delBtn = isManual
      ? `<button class="delete-btn" onclick="window.deleteTransfer(${t.id}, this)" title="Remove entry">🗑</button>`
      : '';

    return `<tr>
      <td style="white-space:nowrap">${fmtDate(t.transfer_date)}</td>
      <td class="${dirCls}">${t.direction.charAt(0).toUpperCase() + t.direction.slice(1)}</td>
      <td class="num-col">${fmtMoney(t.amount)}</td>
      <td class="${stCls}">${t.status.charAt(0).toUpperCase() + t.status.slice(1)}</td>
      <td>${src}</td>
      <td style="color:var(--muted);font-size:12px">${t.notes || ''}</td>
      <td class="xfer-actions">${clearBtn}${delBtn}</td>
    </tr>`;
  }
}
