// ── Shared Utilities ───────────────────────────────────────────────
function fmtDate(s) {
  if (!s) return '--';
  try { const [y, m, d] = s.split('-'); return parseInt(m) + '/' + parseInt(d) + '/' + y; }
  catch(e) { return s; }
}

function fmtTime(iso) {
  if (!iso) return '--';
  try {
    const d = new Date(iso);
    return d.toLocaleDateString('en-US', {month:'short', day:'numeric'}) + ' ' +
           d.toLocaleTimeString('en-US', {hour:'2-digit', minute:'2-digit'});
  } catch(e) { return iso; }
}

function fmtMoney(v) {
  return '$' + parseFloat(v || 0).toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2});
}
