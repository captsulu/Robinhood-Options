/**
 * CoveredCallScan.js
 * Prototype extensions for CoveredCallManager:
 *   triggerScan(btn)     — POST to /api/covered-calls/scan
 *   stopScan()           — POST to /api/covered-calls/scan/stop
 *   _startProgressPoll() — begin 3-second polling loop
 *   _pollStatus()        — GET /api/covered-calls/scan/status
 *   _renderProgress(p)   — update progress bar and status indicators
 *
 * Depends on: CoveredCallCore.js (must load first)
 */

/** Start a covered-call scan (grades A + B by default). */
CoveredCallManager.prototype.triggerScan = function(btn) {
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Starting…'; }
  var stopBtn = document.getElementById('ccStopBtn');
  if (stopBtn) stopBtn.style.display = 'inline-block';

  var self = this;
  fetch('/api/covered-calls/scan', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ grades: ['A', 'B'] }),
  })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (!data.success) {
        alert(data.message || 'Could not start scan');
        if (btn) { btn.disabled = false; btn.textContent = '📞 Scan Opportunities'; }
        if (stopBtn) stopBtn.style.display = 'none';
        return;
      }
      self._startProgressPoll();
    })
    .catch(function() {
      if (btn) { btn.disabled = false; btn.textContent = '📞 Scan Opportunities'; }
      if (stopBtn) stopBtn.style.display = 'none';
    });
};

/** Stop a running scan. */
CoveredCallManager.prototype.stopScan = function() {
  fetch('/api/covered-calls/scan/stop', { method: 'POST' });
  var stopBtn = document.getElementById('ccStopBtn');
  if (stopBtn) stopBtn.style.display = 'none';
};

/** Begin polling the scan status every 3 seconds. */
CoveredCallManager.prototype._startProgressPoll = function() {
  if (this._pollInterval) clearInterval(this._pollInterval);
  var self = this;
  this._pollInterval = setInterval(function() { self._pollStatus(); }, 3000);
};

/** Fetch scan status and forward to _renderProgress. */
CoveredCallManager.prototype._pollStatus = function() {
  var self = this;
  fetch('/api/covered-calls/scan/status')
    .then(function(r) { return r.json(); })
    .then(function(p) { self._renderProgress(p); })
    .catch(function() {});
};

/** Update progress bar, status badge, and scan/stop buttons. */
CoveredCallManager.prototype._renderProgress = function(p) {
  var wrap    = document.getElementById('ccScanProgress');
  var bar     = document.getElementById('ccScanBar');
  var text    = document.getElementById('ccScanProgressText');
  var status  = document.getElementById('ccScanStatus');
  var scanBtn = document.getElementById('ccScanBtn');
  var stopBtn = document.getElementById('ccStopBtn');

  if (p.running) {
    if (wrap)    wrap.classList.remove('hidden');
    if (bar) {
      var pct = p.total > 0 ? Math.round(p.done / p.total * 100) : 0;
      bar.style.width = pct + '%';
      if (text) {
        text.textContent =
          p.done.toLocaleString() + ' / ' + p.total.toLocaleString() +
          ' (' + pct + '%)  ·  ' + p.current +
          (p.found > 0 ? '  ·  ' + p.found + ' found' : '');
      }
    }
    if (status) { status.className = 'ss-scan-status ss-scan-running'; status.textContent = '📞 Scanning…'; }
    if (scanBtn) { scanBtn.disabled = true;  scanBtn.textContent = '⏳ Scanning…'; }
    if (stopBtn) stopBtn.style.display = 'inline-block';
  } else {
    if (wrap)    wrap.classList.add('hidden');
    if (status)  status.className = 'ss-scan-status hidden';
    if (scanBtn) { scanBtn.disabled = false; scanBtn.textContent = '📞 Scan Opportunities'; }
    if (stopBtn) stopBtn.style.display = 'none';

    // Reload data when a scan just finished
    if (p.finished_at && p.finished_at !== this._lastFinish) {
      this.loadStats();
      this.load();
    }
    this._lastFinish = p.finished_at;
  }
};
