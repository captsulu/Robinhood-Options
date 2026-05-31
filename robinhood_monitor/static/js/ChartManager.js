/**
 * ChartManager
 * Renders Chart.js price-history charts with tolerance-band overlays
 * for each unique symbol in the positions list.
 * Depends on: app.positions, app.tolerance, app.pos.getStrikeMap(), fmtTime()
 */
class ChartManager {
  /** @param {MonitorApp} app */
  constructor(app) {
    this.app     = app;
    /** @type {Object.<string, Chart>} symbol → Chart.js instance */
    this._charts = {};
  }

  // ── Public API ───────────────────────────────────────────────────

  /** Convenience method — called by the period <select> onchange handler. */
  refresh() {
    if (this.app.positions.length) this.render();
  }

  /**
   * Syncs chart wrappers to the current position list, then fetches and
   * draws price history for each symbol.
   */
  render() {
    const symbols   = [...new Set(this.app.positions.map(p => p.symbol))];
    const hours     = this._getSelectedHours();
    const container = document.getElementById('chartsContainer');

    this._syncChartWrappers(symbols, container);

    symbols.forEach(sym => {
      fetch(`/api/history/${sym}?hours=${hours}`)
        .then(r => r.json())
        .then(rows => this._draw(sym, rows));
    });
  }

  // ── Private helpers ──────────────────────────────────────────────

  _getSelectedHours() {
    const el = document.getElementById('chartHours');
    return el ? (parseInt(el.value) || 24) : 24;
  }

  /** Adds wrappers for new symbols and removes wrappers for gone ones. */
  _syncChartWrappers(symbols, container) {
    // Add missing wrappers
    symbols.forEach(sym => {
      if (!document.getElementById(`chart-${sym}`)) {
        const wrap = document.createElement('div');
        wrap.className   = 'chart-wrap';
        wrap.dataset.sym = sym;
        wrap.innerHTML   = `<h3 class="chart-title">${sym}</h3>
                            <div class="canvas-wrap">
                              <canvas id="chart-${sym}"></canvas>
                            </div>`;
        container.appendChild(wrap);
      }
    });

    // Remove stale wrappers
    container.querySelectorAll('.chart-wrap').forEach(wrap => {
      if (!symbols.includes(wrap.dataset.sym)) {
        wrap.remove();
        delete this._charts[wrap.dataset.sym];
      }
    });
  }

  /**
   * Draws (or redraws) the Chart.js instance for a symbol.
   * @param {string} symbol
   * @param {Array}  rows  - [{recorded_at, price}, ...]
   */
  _draw(symbol, rows) {
    const canvas = document.getElementById(`chart-${symbol}`);
    if (!canvas) return;

    if (this._charts[symbol]) {
      this._charts[symbol].destroy();
      delete this._charts[symbol];
    }

    const strikes = this.app.pos.getStrikeMap()[symbol] || [];
    const tol     = this.app.tolerance / 100;
    const labels  = rows.map(r => fmtTime(r.recorded_at));
    const prices  = rows.map(r => r.price);

    this._charts[symbol] = new Chart(canvas, {
      type: 'line',
      data: {
        labels,
        datasets: [{
          label:           `${symbol} Price`,
          data:            prices,
          borderColor:     '#58a6ff',
          backgroundColor: 'rgba(88,166,255,0.07)',
          borderWidth:     2,
          pointRadius:     rows.length > 120 ? 0 : 2,
          tension:         0.2,
          fill:            true,
        }],
      },
      options: {
        responsive:          true,
        maintainAspectRatio: false,
        animation:           false,
        scales: {
          x: { ticks: { color: '#8b949e', maxTicksLimit: 8, maxRotation: 0 }, grid: { color: '#21262d' } },
          y: { ticks: { color: '#8b949e', callback: v => `$${v.toFixed(2)}` }, grid: { color: '#21262d' } },
        },
        plugins: {
          legend:  { labels: { color: '#c9d1d9' } },
          tooltip: { callbacks: { label: ctx => ` $${ctx.parsed.y.toFixed(4)}` } },
        },
      },
      plugins: [this._buildStrikePlugin(strikes, tol)],
    });
  }

  /**
   * Builds a Chart.js plugin that draws strike-price lines and tolerance bands.
   * @param {number[]} strikes
   * @param {number}   tol  - tolerance as a decimal (e.g. 0.02)
   * @returns {Object} Chart.js plugin object
   */
  _buildStrikePlugin(strikes, tol) {
    return {
      id: 'strikeLines',
      afterDraw(chart) {
        const { ctx, chartArea, scales } = chart;
        if (!chartArea || !scales.y) return;

        strikes.forEach(strike => {
          const yCenter = scales.y.getPixelForValue(strike);
          const yUpper  = scales.y.getPixelForValue(strike * (1 + tol));
          const yLower  = scales.y.getPixelForValue(strike * (1 - tol));
          const zoneTop = Math.min(yUpper, yLower);
          const zoneH   = Math.abs(yUpper - yLower);

          ctx.save();
          // Tolerance zone shading
          ctx.fillStyle = 'rgba(248,81,73,0.09)';
          ctx.fillRect(chartArea.left, zoneTop, chartArea.right - chartArea.left, zoneH);
          // Dashed strike line
          ctx.beginPath();
          ctx.setLineDash([8, 4]);
          ctx.strokeStyle = '#f85149';
          ctx.lineWidth   = 1.5;
          ctx.moveTo(chartArea.left,  yCenter);
          ctx.lineTo(chartArea.right, yCenter);
          ctx.stroke();
          ctx.setLineDash([]);
          // Strike label
          ctx.fillStyle    = '#f85149';
          ctx.font         = 'bold 11px Segoe UI, system-ui, sans-serif';
          ctx.textAlign    = 'right';
          ctx.textBaseline = 'bottom';
          ctx.fillText(`Strike $${strike.toFixed(2)}`, chartArea.right - 4, yCenter - 2);
          ctx.restore();
        });
      },
    };
  }
}
