/**
 * TabManager
 * Controls tab switching, the settings overlay, collapsible sections,
 * the scan trigger, and saving/loading app configuration.
 * Also owns the main refresh orchestration and header update logic.
 * Depends on: app.pos, app.cash, app.charts, app.transfers, app.logs
 */
class TabManager {
  /** @param {MonitorApp} app */
  constructor(app) {
    this.app           = app;
    this._settingsOpen = false;
  }

  // ── Tab switching ────────────────────────────────────────────────

  /**
   * Activates the named tab pane and highlights its nav button.
   * Triggers lazy-loading for data-heavy tabs on first visit.
   * @param {string} name - 'dashboard' | 'collateral' | 'transfers' | 'logs'
   */
  showTab(name) {
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.add('hidden'));
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.getElementById('pane-' + name).classList.remove('hidden');
    document.getElementById('tab-'  + name).classList.add('active');
    try { localStorage.setItem('activeTab', name); } catch (e) { /* storage unavailable */ }

    if (name === 'funds') {
      this.app.cash.refresh();
      this.app.transfers.refresh();
    }
    if (name === 'logs') {
      this.app.logs.loadAlerts();
      this.app.logs.loadCashHistory();
    }
    if (name === 'transfers') {
      this.app.transfers.refresh();
    }
    if (name === 'collateral') {
      this.app.pos.renderCollateralBreakdown(
        this.app.positions,
        this.app.lastTotalCollateral || 0
      );
    }
    if (name === 'stockscreen') {
      // Lazy-init on first visit, then just refresh stats on subsequent visits
      if (!this._stockScreenInitialised) {
        this._stockScreenInitialised = true;
        this.app.stockScreen.init();
      } else {
        this.app.stockScreen.loadStats();
      }
    }
    if (name === 'putscreen') {
      if (!this._putScreenInitialised) {
        this._putScreenInitialised = true;
        this.app.putScreen.init();
      } else {
        this.app.putScreen.loadStats();
      }
    }
    if (name === 'coveredcalls') {
      if (!this._ccInitialised) {
        this._ccInitialised = true;
        this.app.coveredCalls.init();
      } else {
        this.app.coveredCalls.loadStats();
      }
    }
  }

  // ── Settings overlay ─────────────────────────────────────────────

  /** Toggles the settings overlay open/closed. */
  toggleSettings() {
    this._settingsOpen = !this._settingsOpen;
    document.getElementById('settingsOverlay')
      .classList.toggle('hidden', !this._settingsOpen);
  }

  /**
   * Loads persisted config from the server and populates the settings form.
   * Also updates the tolerance card label and shared app.tolerance.
   */
  loadSettings() {
    fetch('/api/config')
      .then(r => r.json())
      .then(cfg => {
        this.app.tolerance = parseFloat(cfg.tolerance_percent) || 2.0;
        document.getElementById('tolSlider').value       = this.app.tolerance;
        document.getElementById('tolValue').textContent  = this.app.tolerance.toFixed(1) + '%';
        document.getElementById('dteInput').value        = cfg.days_before_expiration_warning || 3;
        document.getElementById('scanInput').value       = cfg.scan_interval_minutes || 5;
        document.getElementById('emailToggle').checked   = !!cfg.email_enabled;
        document.getElementById('emailAddr').value       = cfg.email_address || '';
        document.getElementById('emailAddr').disabled    = !cfg.email_enabled;
        document.getElementById('cardTolerance').textContent = this.app.tolerance.toFixed(1) + '%';
      })
      .catch(e => console.error('TabManager.loadSettings error:', e));
  }

  /** Reads the settings form, POSTs to /api/config, then triggers a refresh. */
  saveSettings() {
    const payload = {
      tolerance_percent:              parseFloat(document.getElementById('tolSlider').value),
      days_before_expiration_warning: parseInt(document.getElementById('dteInput').value),
      scan_interval_minutes:          parseInt(document.getElementById('scanInput').value),
      email_enabled:                  document.getElementById('emailToggle').checked,
      email_to_address:               document.getElementById('emailAddr').value.trim(),
    };
    fetch('/api/config', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(payload),
    })
      .then(r => r.json())
      .then(res => {
        if (res.success) {
          this.app.tolerance = payload.tolerance_percent;
          document.getElementById('cardTolerance').textContent =
            this.app.tolerance.toFixed(1) + '%';
          this.toggleSettings();
          this.app.refresh();
        }
      })
      .catch(e => console.error('TabManager.saveSettings error:', e));
  }

  // ── Scan trigger ─────────────────────────────────────────────────

  /**
   * Fires a background scan via /api/scan then refreshes positions after a
   * short delay to allow the server-side scan to complete.
   */
  triggerScan() {
    const btn = document.getElementById('scanBtn');
    if (btn) { btn.disabled = true; btn.textContent = '⏳ Scanning…'; }
    fetch('/api/scan', { method: 'POST' })
      .then(() => {
        setTimeout(() => {
          this.app.refresh();
          if (btn) { btn.disabled = false; btn.textContent = '🔄 Scan Now'; }
        }, 3500);
      })
      .catch(e => {
        console.error('TabManager.triggerScan error:', e);
        if (btn) { btn.disabled = false; btn.textContent = '🔄 Scan Now'; }
      });
  }

  // ── Header & alert banner ─────────────────────────────────────────

  /**
   * Updates the page header status, summary cards, and the alert banner.
   * @param {Object} data - response from /api/positions
   */
  updateHeader(data) {
    document.getElementById('sessionLabel').textContent =
      data.session || '';
    document.getElementById('lastScan').textContent =
      data.last_scan ? 'Last scan: ' + fmtTime(data.last_scan) : '';

    const badge = document.getElementById('statusBadge');
    badge.className   = 'badge badge-' + (data.status === 'error' ? 'error' : 'ok');
    badge.textContent = data.status === 'error' ? '✕ Error' : '✓ OK';

    const positions = this.app.positions;
    const safe = positions.filter(p => p.status === 'safe').length;
    const warn = positions.filter(p => p.status === 'warning').length;
    const crit = positions.filter(p => p.status === 'critical').length;

    document.getElementById('cardTotal').textContent    = positions.length;
    document.getElementById('cardSafe').textContent     = safe;
    document.getElementById('cardWarning').textContent  = warn;
    document.getElementById('cardCritical').textContent = crit;
    document.getElementById('cardSession').textContent  = data.session || '--';

    const banner = document.getElementById('alertBanner');
    if (crit > 0) {
      banner.className   = 'alert-banner alert-critical';
      banner.textContent =
        '🚨 ' + crit + ' CRITICAL position' + (crit !== 1 ? 's' : '') +
        ' — immediate attention required!';
    } else if (warn > 0) {
      banner.className   = 'alert-banner alert-warning';
      banner.textContent =
        '⚠️ ' + warn + ' position' + (warn !== 1 ? 's' : '') + ' in WARNING zone';
    } else if (!data.market_open) {
      banner.className   = 'alert-banner alert-info';
      banner.textContent = '🌙 ' + (data.message || 'Outside trading hours');
    } else {
      banner.className = 'alert-banner hidden';
    }
  }

  // ── Collapsible sections ─────────────────────────────────────────

  /**
   * Toggles a collapsible section body open/closed and persists state.
   * @param {string} id - section identifier (e.g. 'cash', 'capital')
   */
  toggleSection(id) {
    const body  = document.getElementById('body-' + id);
    const title = body.previousElementSibling;
    const open  = !body.classList.contains('hidden');
    body.classList.toggle('hidden', open);
    title.classList.toggle('collapsed', open);
    try {
      localStorage.setItem('section-' + id, open ? 'collapsed' : 'open');
    } catch (e) { /* storage unavailable */ }
  }

  /** Restores collapsible-section states from localStorage on page load. */
  restoreSections() {
    ['cash', 'capital'].forEach(id => {
      try {
        const state = localStorage.getItem('section-' + id);
        if (state === 'collapsed') {
          const body  = document.getElementById('body-' + id);
          const title = body.previousElementSibling;
          body.classList.add('hidden');
          title.classList.add('collapsed');
        }
      } catch (e) { /* storage unavailable */ }
    });
  }
}