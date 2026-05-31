/**
 * PositionsManager
 * Renders the options positions table and the collateral breakdown panel.
 * Depends on: app.grades (GradeManager), app.tolerance, fmtDate(), fmtMoney()
 */
class PositionsManager {
  /** @param {MonitorApp} app */
  constructor(app) {
    this.app = app;
    /** @type {Object.<string, number[]>} symbol → [strike, ...] */
    this._strikeMap = {};
  }

  // ── Public API ───────────────────────────────────────────────────

  /** Rebuild the strike price map used by ChartManager. */
  buildStrikeMap(positions) {
    this._strikeMap = {};
    positions.forEach(p => {
      if (!this._strikeMap[p.symbol]) this._strikeMap[p.symbol] = [];
      if (!this._strikeMap[p.symbol].includes(p.strike_price)) {
        this._strikeMap[p.symbol].push(p.strike_price);
      }
    });
  }

  /** Returns the strike map (consumed by ChartManager). */
  getStrikeMap() {
    return this._strikeMap;
  }

  /**
   * Re-renders the positions tbody.
   * Splits 0DTE positions into the top 0DTE section and the rest into the main table.
   * Triggers background grade fetches for each unique symbol.
   * @param {Array} positions
   */
  renderTable(positions) {
    const zdteSection = document.getElementById('zdte-section');
    const zdteBody    = document.getElementById('zdteBody');
    const tbody       = document.getElementById('positionsBody');

    if (!positions.length) {
      if (zdteSection) zdteSection.classList.add('hidden');
      tbody.innerHTML = '<tr><td colspan="13" class="empty-msg">No open positions</td></tr>';
      return;
    }

    // Build group colours across ALL positions so spread legs
    // stay consistently colour-coded even if one leg is 0DTE.
    const groupColor = this._buildGroupColors(positions);
    const zdte       = positions.filter(p => p.dte === 0);
    const regular    = positions.filter(p => p.dte !== 0);

    // Kick off background grade fetches for every unique symbol
    const seen = new Set();
    positions.forEach(p => {
      if (!seen.has(p.symbol)) {
        seen.add(p.symbol);
        this.app.grades.fetchGrade(p.symbol);
      }
    });

    // ── 0DTE section ─────────────────────────────────────────────────
    if (zdteSection) {
      if (zdte.length > 0) {
        zdteSection.classList.remove('hidden');
        zdteBody.innerHTML = zdte.map(p => this._buildRow(p, groupColor)).join('');
      } else {
        zdteSection.classList.add('hidden');
      }
    }

    // ── Regular (non-0DTE) positions ──────────────────────────────────
    tbody.innerHTML = regular.length
      ? regular.map(p => this._buildRow(p, groupColor)).join('')
      : '<tr><td colspan="13" class="empty-msg">No open positions</td></tr>';
  }

  /**
   * Updates the collateral card on the Dashboard tab and the full breakdown
   * table on the Collateral tab.
   * @param {Array}  positions
   * @param {number} totalCollateral
   */
  renderCollateralBreakdown(positions, totalCollateral) {
    this.app.lastTotalCollateral = totalCollateral;

    // Dashboard card
    const dashCard = document.getElementById('cashCollateral');
    if (dashCard) {
      dashCard.textContent = positions.length > 0 ? fmtMoney(totalCollateral) : '--';
    }

    // Collateral tab summary cards (synced here; also synced by CashManager)
    this._syncCollateralTabCards(totalCollateral);

    // Breakdown table
    const breakdown = document.getElementById('collateralBreakdown');
    if (!breakdown) return;

    const withCollateral = positions.filter(p => (p.collateral || 0) > 0);
    if (!withCollateral.length) {
      breakdown.innerHTML = positions.length === 0
        ? '<p class="hint">No positions loaded yet — run a scan first.</p>'
        : '<p class="hint">No cash collateral required by current positions. Covered calls use stock as collateral.</p>';
      return;
    }

    breakdown.innerHTML = this._buildCollateralTable(withCollateral, totalCollateral);
  }

  // ── Badge helpers (also used by LogManager) ──────────────────────

  /** @param {Object} p - position object */
  strategyBadge(p) {
    const leg = p.spread_leg === 'long' ? ' ▲' : p.spread_leg === 'short' ? ' ▼' : '';
    const map = {
      covered_call:     ['covered-call',  'Covered Call'],
      call_spread:      ['call-spread',   `Call Spread${leg}`],
      put_spread:       ['put-spread',    `Put Spread${leg}`],
      cash_secured_put: ['csp',           'CSP'],
      long_call:        ['long-call',     'Long Call'],
      long_put:         ['long-put',      'Long Put'],
      naked_call:       ['naked-call',    'Naked Call'],
    };
    const [cls, label] = map[p.strategy] || ['unknown-strat', p.strategy || 'Unknown'];
    return `<span class="badge-strategy ${cls}">${label}</span>`;
  }

  /** @param {string} s - status string */
  statusBadge(s) {
    const labels = { safe: '✓ Safe', warning: '⚠ Warning', critical: '🚨 Critical', unknown: '? Unknown' };
    return `<span class="badge-status ${s}">${labels[s] || s}</span>`;
  }

  // ── Private helpers ──────────────────────────────────────────────

  _buildGroupColors(positions) {
    const groupColor = {};
    let ci = 0;
    positions.forEach(p => {
      if (p.spread_group && !(p.spread_group in groupColor)) {
        groupColor[p.spread_group] = (ci++ % 2 === 0) ? 'spread-a' : 'spread-b';
      }
    });
    return groupColor;
  }

  _buildRow(p, groupColor) {
    const tol      = this.app.tolerance;
    const distSign = p.distance_pct >= 0 ? '+' : '';
    const distCls  = p.distance_pct < 0
      ? 'critical'
      : Math.abs(p.distance_pct) <= tol ? 'warning' : 'safe';
    const dteCls   = (p.dte !== null && p.dte <= 3) ? 'text-critical'
                   : p.dte <= 7 ? 'text-warning' : '';
    const groupCls = p.spread_group
      ? `spread-row ${groupColor[p.spread_group] || ''}`
      : '';

    const colCell    = this._buildCollateralCell(p);
    const statusCell = p.spread_leg === 'long'
      ? '<span class="badge-status protected">🛡 Protected</span>'
      : this.statusBadge(p.status);

    return `<tr class="${groupCls} row-${p.status}">
      <td class="sym-col">${p.symbol}</td>
      <td style="white-space:nowrap">${this.app.grades.gradeBtn(p.symbol)}</td>
      <td>${this.strategyBadge(p)}</td>
      <td>${p.type.charAt(0).toUpperCase() + p.type.slice(1)}
          <span class="pos-type ${p.position_type}">${p.position_type === 'long' ? 'Buy' : 'Sell'}</span></td>
      <td class="num-col">$${p.strike_price.toFixed(2)}</td>
      <td>${fmtDate(p.expiration_date)}</td>
      <td class="num-col ${dteCls}">${p.dte !== null ? p.dte + 'd' : '--'}</td>
      <td class="num-col">${p.quantity}</td>
      <td class="num-col">$${p.average_price.toFixed(2)}</td>
      <td class="num-col">$${p.current_price.toFixed(2)}</td>
      <td class="num-col ${p.spread_leg === 'long' ? 'text-muted-leg' : 'text-' + distCls}">
          ${distSign}${p.distance_pct.toFixed(1)}%</td>
      <td class="num-col">${colCell}</td>
      <td>${statusCell}</td>
    </tr>`;
  }

  _buildCollateralCell(p) {
    const col     = p.collateral || 0;
    const colType = p.collateral_type || '';
    if (col > 0) {
      return `<span style="color:var(--orange);font-weight:600;">${fmtMoney(col)}</span>`;
    }
    if (colType === 'stock_secured') {
      return '<span style="color:var(--muted);font-size:11px;">Stock</span>';
    }
    return '<span style="color:var(--muted);font-size:11px;">—</span>';
  }

  _syncCollateralTabCards(totalCollateral) {
    const live     = this.app.cash.getLive();
    const tabTotal = document.getElementById('colTabTotal');
    const tabWith  = document.getElementById('colTabWithdrawable');
    const tabCash  = document.getElementById('colTabCash');
    const tabFree  = document.getElementById('colTabFree');

    if (tabTotal) tabTotal.textContent = fmtMoney(totalCollateral);
    if (live) {
      if (tabWith) tabWith.textContent = fmtMoney(live.cash_available_for_withdrawal);
      if (tabCash) tabCash.textContent = fmtMoney(live.cash);
      if (tabFree) {
        const free = parseFloat(live.cash || 0) - totalCollateral;
        tabFree.textContent = fmtMoney(free);
        tabFree.style.color = free >= 0 ? '' : 'var(--red)';
      }
    }
  }

  _buildCollateralTable(withCollateral, totalCollateral) {
    const typeLabels = {
      cash_secured:    'CSP — full strike',
      spread_max_loss: 'Spread — max loss',
    };

    const rows = withCollateral.map(p => {
      const typeLabel = typeLabels[p.collateral_type] || p.collateral_type || '';
      const dteLbl    = p.dte !== null ? `${p.dte}d` : '--';
      const dteCls    = (p.dte !== null && p.dte <= 3) ? 'text-critical'
                      : p.dte <= 7 ? 'text-warning' : '';
      return `<tr>
        <td class="sym-col">${p.symbol}</td>
        <td>${this.strategyBadge(p)}</td>
        <td class="num-col">$${p.strike_price.toFixed(2)}</td>
        <td class="num-col">${p.quantity}</td>
        <td>${fmtDate(p.expiration_date)}</td>
        <td class="num-col ${dteCls}">${dteLbl}</td>
        <td style="font-size:11px;color:var(--muted);">${typeLabel}</td>
        <td class="num-col" style="color:var(--orange);font-weight:700;">${fmtMoney(p.collateral)}</td>
      </tr>`;
    }).join('');

    const total = `<tfoot>
      <tr style="border-top:2px solid var(--border)">
        <td colspan="7" style="padding:9px 12px;font-weight:700;color:var(--muted);
            font-size:12px;text-transform:uppercase;letter-spacing:.04em;">Total locked</td>
        <td class="num-col" style="padding:9px 12px;font-weight:700;
            color:var(--orange);font-size:16px;">${fmtMoney(totalCollateral)}</td>
      </tr>
    </tfoot>`;

    return `<div class="table-wrap"><table>
      <thead><tr>
        <th>Symbol</th><th>Strategy</th><th>Strike</th><th>Qty</th>
        <th>Expiration</th><th>DTE</th><th>Collateral Type</th><th>Cash Locked</th>
      </tr></thead>
      <tbody>${rows}</tbody>
      ${total}
    </table></div>`;
  }
}
