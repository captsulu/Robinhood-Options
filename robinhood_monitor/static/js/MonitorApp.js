/**
 * MonitorApp
 * Root application object — instantiates all manager classes, owns shared
 * mutable state, and orchestrates the primary data-fetch/render cycle.
 *
 * Shared state (read by multiple managers):
 *   app.tolerance          — current tolerance % (number, e.g. 2.0)
 *   app.positions          — last fetched positions array
 *   app.lastTotalCollateral — total locked cash collateral (number)
 *
 * Manager instances:
 *   app.grades    — GradeManager
 *   app.pos       — PositionsManager
 *   app.cash      — CashManager
 *   app.charts    — ChartManager
 *   app.transfers — TransferManager
 *   app.logs      — LogManager
 *   app.tabs      — TabManager
 */
class MonitorApp {
  constructor() {
    // ── Shared state ───────────────────────────────────────────────
    /** @type {number} Tolerance band in percent (e.g. 2.0 = 2%) */
    this.tolerance           = 2.0;
    /** @type {Array}  Last fetched positions list */
    this.positions           = [];
    /** @type {number} Last computed total cash collateral */
    this.lastTotalCollateral = 0;

    // ── Manager instances ──────────────────────────────────────────
    // GradeManager has no app dependency (self-contained cache + sidebar)
    this.grades      = new GradeManager();
    this.pos         = new PositionsManager(this);
    this.cash        = new CashManager(this);
    this.charts      = new ChartManager(this);
    this.transfers   = new TransferManager(this);
    this.logs        = new LogManager(this);
    this.tabs        = new TabManager(this);
    this.stockScreen = new StockScreenManager(this);
    this.putScreen   = new PutScreenManager(this);
    this.coveredCalls = new CoveredCallManager(this);
  }

  // ── Bootstrap ────────────────────────────────────────────────────

  /**
   * Initialises the application after the DOM is ready.
   * Called once from main.js inside DOMContentLoaded.
   */
  init() {
    // Load persisted settings from server (tolerance, DTE, email, etc.)
    this.tabs.loadSettings();

    // Restore collapsible-section open/close states
    this.tabs.restoreSections();

    // Restore margin toggle preference before the first cash render
    try {
      const saved = localStorage.getItem('bpMargin');
      if (saved !== null) {
        document.getElementById('marginToggle').checked = (saved === '1');
      }
    } catch (e) { /* storage unavailable */ }

    // Wire the tolerance slider to its live label
    document.getElementById('tolSlider').addEventListener('input', function () {
      document.getElementById('tolValue').textContent =
        parseFloat(this.value).toFixed(1) + '%';
    });

    // Wire the email toggle to enable/disable the address field
    document.getElementById('emailToggle').addEventListener('change', function () {
      document.getElementById('emailAddr').disabled = !this.checked;
    });

    // Initial data loads
    this.refresh();
    this.cash.refresh();
    this.transfers.refresh();

    // Restore the last active tab (must run after managers are ready)
    let savedTab = 'dashboard';
    try { savedTab = localStorage.getItem('activeTab') || 'dashboard'; } catch (e) {}
    this.tabs.showTab(savedTab);

    // Auto-refresh intervals
    setInterval(() => this.refresh(),           30000);  //  30 s — positions
    setInterval(() => this.cash.refresh(),      60000);  //  60 s — cash
    setInterval(() => this.transfers.refresh(), 120000); // 120 s — transfers
  }

  // ── Core refresh ─────────────────────────────────────────────────

  /**
   * Fetches /api/positions and orchestrates a full UI update:
   * header, positions table, collateral breakdown, and charts.
   */
  refresh() {
    fetch('/api/positions')
      .then(r => r.json())
      .then(data => {
        this.positions           = data.positions || [];
        this.lastTotalCollateral = data.total_collateral || 0;

        this.tabs.updateHeader(data);
        this.pos.buildStrikeMap(this.positions);
        this.pos.renderTable(this.positions);
        this.pos.renderCollateralBreakdown(this.positions, this.lastTotalCollateral);
        this.charts.render();
      })
      .catch(e => console.error('MonitorApp.refresh error:', e));
  }
}
