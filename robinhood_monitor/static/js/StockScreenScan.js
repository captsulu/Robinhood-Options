/**
 * StockScreenScan.js
 * Prototype extensions for StockScreenManager — scan control and progress polling.
 * Must load AFTER StockScreenCore.js.
 *
 * Methods added:
 *   triggerScan(btn)    — POST to start a full scan
 *   stopScan()          — POST to stop a running scan
 *   _startProgressPoll()
 *   _pollScanStatus()
 *   _renderScanProgress(p)
 */

StockScreenManager.prototype.triggerScan = function(btn) {
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Starting…'; }
  fetch('/api/stock-universe/scan', { method: 'POST' })
    .then(r => r.json())
    .then(data => {
      if (!data.success) {
        alert(data.message || 'Could not start scan');
        if (btn) { btn.disabled = false; btn.textContent = '⚡ Run Full Scan'; }
      }
      this._startProgressPoll();
    })
    .catch(() => {
      if (btn) { btn.disabled = false; btn.textContent = '⚡ Run Full Scan'; }
    });
};

StockScreenManager.prototype.stopScan = function() {
  fetch('/api/stock-universe/scan/stop', { method: 'POST' });
};

StockScreenManager.prototype._startProgressPoll = function() {
  if (this._pollInterval) clearInterval(this._pollInterval);
  this._pollInterval = setInterval(() => this._pollScanStatus(), 3000);
};

StockScreenManager.prototype._pollScanStatus = function() {
  fetch('/api/stock-universe/scan/status')
    .then(r => r.json())
    .then(p => this._renderScanProgress(p))
    .catch(() => {});
};

StockScreenManager.prototype._renderScanProgress = function(p) {
  const wrap    = document.getElementById('ssScanProgress');
  const bar     = document.getElementById('ssScanBar');
  const text    = document.getElementById('ssScanProgressText');
  const status  = document.getElementById('ssScanStatus');
  const scanBtn = document.getElementById('ssScanBtn');

  if (p.running) {
    wrap?.classList.remove('hidden');
    const pct = p.total > 0 ? Math.round(p.done / p.total * 100) : 0;
    if (bar)  bar.style.width  = pct + '%';
    if (text) text.textContent =
      `${p.done.toLocaleString()} / ${p.total.toLocaleString()} (${pct}%)  ·  ${p.current}`;
    if (status) {
      status.className   = 'ss-scan-status ss-scan-running';
      status.textContent = '⚡ Scanning…';
    }
    if (scanBtn) { scanBtn.disabled = true; scanBtn.textContent = '⏳ Scanning…'; }
  } else {
    wrap?.classList.add('hidden');
    if (status)  status.className = 'ss-scan-status hidden';
    if (scanBtn) { scanBtn.disabled = false; scanBtn.textContent = '⚡ Run Full Scan'; }
    if (p.finished_at && p.finished_at !== this._lastFinish) {
      this.loadStats();
      this.load();
    }
    this._lastFinish = p.finished_at;
  }
};
