/**
 * main.js -- Application entry point
 *
 * Instantiates MonitorApp, exposes global window bridges so that inline
 * HTML onclick="..." attributes can call into the OOP layer, then boots
 * the app once the DOM is ready.
 *
 * Load order (see dashboard.html):
 *   utils.js -> GradeManager.js -> PositionsManager.js -> CashManager.js
 *   -> ChartManager.js -> TransferManager.js -> LogManager.js
 *   -> TabManager.js -> MonitorApp.js -> StockScreenManager.js -> main.js
 */
document.addEventListener('DOMContentLoaded', () => {
  const app = new MonitorApp();

  // -- Window bridges ----------------------------------------------------
  // HTML onclick attributes cannot call instance methods directly, so we
  // expose thin forwarding functions on window.

  // Grade sidebar (positions table)
  window.openGradeSidebar  = (sym) => app.grades.openSidebar(sym);
  window.closeGradeSidebar = ()    => app.grades.closeSidebar();
  window.refreshGrade      = (sym) => app.grades.refreshGrade(sym, () => {
    app.pos.renderTable(app.positions);
  });

  // Transfer actions
  window.markCleared    = (id, btn) => app.transfers.markCleared(id, btn);
  window.syncTransfers  = (btn)     => app.transfers.sync(btn);
  window.deleteTransfer = (id, btn) => app.transfers.deleteTransfer(id, btn);

  // Header / scan
  window.triggerScan    = () => app.tabs.triggerScan();
  window.toggleSettings = () => app.tabs.toggleSettings();
  window.saveSettings   = () => app.tabs.saveSettings();

  // Tab navigation
  window.showTab = (name) => app.tabs.showTab(name);

  // Cash section
  window.refreshCash    = () => app.cash.refresh();
  window.onMarginToggle = () => app.cash.onMarginToggle();

  // Collapsible sections
  window.toggleSection = (id) => app.tabs.toggleSection(id);

  // Logs tab
  window.takeManualSnapshot = () => app.logs.takeManualSnapshot();

  // Chart period selector
  window.refreshCharts = () => app.charts.refresh();

  // Stock screen -- expose the manager instance directly for the template
  window.stockScreen = app.stockScreen;

  // Put screen -- expose the manager instance directly for the template
  window.putScreen = app.putScreen;
  window.coveredCalls = app.coveredCalls;

  // -- Boot --------------------------------------------------------------
  app.init();
});
