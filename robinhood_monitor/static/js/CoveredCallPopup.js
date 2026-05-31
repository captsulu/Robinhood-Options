/**
 * CoveredCallPopup.js
 * Prototype extensions for CoveredCallManager:
 *   openPopup(symbol)  — builds and shows the per-ticker options popup
 *   closePopup()       — hides the popup
 *
 * Depends on: CoveredCallCore.js (must load first), fmtMoney()
 */

/** Open the per-ticker options popup grouped by expiration date. */
CoveredCallManager.prototype.openPopup = function(symbol) {
  const rows = this._grouped[symbol];
  if (!rows || !rows.length) return;

  const r0    = rows[0];
  const price = r0.current_price != null ? fmtMoney(r0.current_price) : '—';
  const cost  = r0.current_price != null ? fmtMoney(r0.current_price * 100) : '—';

  // ── Header affordability / ownership badges ───────────────────────
  const canAfford = this._availCash !== null && r0.current_price * 100 <= this._availCash;
  const affordTxt = this._availCash !== null
    ? '<span style="font-size:12px;margin-left:10px;' +
      (canAfford ? 'color:var(--green)' : 'color:var(--red)') + '">' +
      (canAfford ? '✓ Affordable' : '✗ Over budget') +
      ' — ' + cost + ' for 100 shares</span>'
    : '<span style="font-size:12px;color:var(--muted);margin-left:10px">' +
      cost + ' for 100 shares</span>';

  const ownedTxt = this._ownedSet.has(symbol)
    ? '<span style="color:var(--orange);font-size:12px;margin-left:10px">⚠ Already in portfolio</span>'
    : '';

  document.getElementById('ccPopupTitle').innerHTML =
    '<span style="font-size:18px;font-weight:700">' + symbol + '</span>' +
    '<span style="color:var(--muted);font-size:14px;margin-left:8px">— ' + (r0.company_name || '') + '</span>' +
    '<span style="color:var(--muted);font-size:13px;margin-left:10px">' + price + '/share</span>' +
    affordTxt + ownedTxt;

  document.getElementById('ccPopupGrade').innerHTML =
    '<button class="grade-btn ' + this.app.grades.gradeColor(r0.grade) + '" ' +
    'onclick="window.stockScreen.openModal(\'' + symbol + '\')" ' +
    'title="Graham Grade: ' + (r0.grade || '?') + '">' + (r0.grade || '?') + '</button>';

  // ── Group rows by expiration date ─────────────────────────────────
  const byExp = {};
  rows.forEach(function(r) {
    if (!byExp[r.expiration]) byExp[r.expiration] = [];
    byExp[r.expiration].push(r);
  });
  // Sort each expiration bucket by ann.roi desc
  Object.values(byExp).forEach(function(arr) {
    arr.sort(function(a, b) { return (b.annualised_roi || 0) - (a.annualised_roi || 0); });
  });

  const critMap  = { delta20: '20Δ', otm20: '20%OTM', cheap: '≤$10' };
  const tierIcon = { legendary: '🏆', epic: '⚡', rare: '💎', good: '✓', other: '·' };

  // ── Build HTML table rows ─────────────────────────────────────────
  var html = '';
  Object.keys(byExp).sort().forEach(function(exp) {
    var expRows  = byExp[exp];
    var expLabel = new Date(exp + 'T12:00:00').toLocaleDateString('en-US',
      { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' });
    var strikeCount = expRows.length;

    html += '<tr>' +
      '<td colspan="9" style="padding:6px 12px;font-weight:700;font-size:12px;' +
      'color:var(--blue);background:rgba(88,166,255,.08);' +
      'letter-spacing:.04em;border-bottom:1px solid var(--border);">' +
      '📅 ' + expLabel + ' &nbsp;·&nbsp; ' + expRows[0].dte + 'd to expiry' +
      ' &nbsp;·&nbsp; ' + strikeCount + ' strike' + (strikeCount !== 1 ? 's' : '') +
      '</td></tr>';

    expRows.forEach(function(r) {
      var strikeLbl = r.strike != null ? '$' + r.strike.toFixed(2) : '—';
      var otmLbl    = r.otm_pct != null ? r.otm_pct.toFixed(1) + '%' : '—';
      var premSh    = r.premium_per_share != null ? '$' + r.premium_per_share.toFixed(2) : '—';
      var prem100   = r.premium_per_share != null ? fmtMoney(r.premium_per_share * 100) : '—';
      var deltaLbl  = r.delta != null ? r.delta.toFixed(3) : '—';
      var ivLbl     = r.iv    != null ? r.iv.toFixed(1) + '%' : '—';
      var aroiLbl   = r.annualised_roi != null ? r.annualised_roi.toFixed(1) + '%' : '—';
      var aroiCls   = 'ps-roi-cell ps-roi-' + (r.tier || 'good');
      var tIcon     = tierIcon[r.tier] || '·';
      var crit      = critMap[r.criteria] || r.criteria || '—';

      html += '<tr class="cc-popup-row">' +
        '<td class="num-col" style="font-weight:600">' + strikeLbl + '</td>' +
        '<td class="num-col">' + otmLbl + '</td>' +
        '<td class="num-col">' + premSh + '<span class="ps-per-contract">/sh</span></td>' +
        '<td class="num-col" style="color:var(--green)">' + prem100 +
          '<span class="ps-per-contract">/contract</span></td>' +
        '<td class="num-col">' + deltaLbl + '</td>' +
        '<td class="num-col">' + ivLbl + '</td>' +
        '<td class="num-col ' + aroiCls + '">' + aroiLbl + '</td>' +
        '<td><span class="ps-tier-badge ps-tier-' + (r.tier || 'good') + '">' + tIcon + '</span></td>' +
        '<td><span style="font-size:11px;color:var(--muted)">' + crit + '</span></td>' +
        '</tr>';
    });
  });

  document.getElementById('ccPopupBody').innerHTML = html;
  document.getElementById('ccPopupOverlay').classList.remove('hidden');
  document.getElementById('ccPopup').classList.remove('hidden');
};

/** Close the popup. */
CoveredCallManager.prototype.closePopup = function() {
  document.getElementById('ccPopup').classList.add('hidden');
  document.getElementById('ccPopupOverlay').classList.add('hidden');
};
