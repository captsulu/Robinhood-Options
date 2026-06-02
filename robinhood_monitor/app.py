"""
Robinhood Options Monitor - Flask Web Server
Run: python app.py
Dashboard: http://localhost:5000
"""

import logging
import os
import threading
import time
import webbrowser
from datetime import datetime

import schedule
from flask import Flask, jsonify, render_template, request

from config_manager import load_config, save_config
from database import (get_price_history, get_recent_alerts, get_tracked_symbols,
                      get_cash_snapshots, init_db, prune_old_data,
                      get_transfers, get_capital_summary, seed_initial_transfers,
                      delete_transfer, get_income_summary, get_income_by_month,
                      get_income_trades, get_income_by_symbol,
                      get_stock_universe, get_stock_universe_stats,
                      get_covered_call_opportunities, get_covered_call_scan_time,
                      get_put_opportunities)
from monitor import MonitorEngine, is_trading_window

# Logging
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'monitor.log')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

# Flask app
app = Flask(__name__, template_folder='templates')

_state = {
    'positions':   [],
    'market_open': False,
    'session':     'Starting...',
    'alert_count': 0,
    'last_scan':   None,
    'status':      'starting',
    'message':     'Initialising...',
}
_state_lock = threading.Lock()
_engine = MonitorEngine()


# Background monitor

def _run_scan():
    try:
        result = _engine.run_scan()
        with _state_lock:
            _state.update(result)
            _state['last_scan'] = datetime.now().isoformat()
            _state['status']    = 'ok'
    except Exception as e:
        logger.error(f"Scan error: {e}", exc_info=True)
        with _state_lock:
            _state['status']  = 'error'
            _state['message'] = str(e)


def _run_weekly_stock_scan():
    """Trigger the full stock universe scan (NYSE + Nasdaq + AMEX).
    Designed to run overnight Saturday so results are ready for Monday open."""
    try:
        from stock_universe_scanner import StockUniverseScanner
        scanner = StockUniverseScanner()
        logger.info("Weekly stock universe scan started (Saturday night schedule)")
        scanner.run_full_scan()
        logger.info("Weekly stock universe scan complete")
    except Exception as e:
        logger.error(f"Weekly stock scan error: {e}", exc_info=True)


def _background_monitor():
    config   = load_config()
    interval = max(1, config.get('scan_interval_minutes', 5))
    logger.info(f"Background monitor started - scanning every {interval} min")
    _run_scan()
    schedule.every(interval).minutes.do(_run_scan)

    # Weekly stock universe scan — Saturday at 01:00 local time
    schedule.every().saturday.at("01:00").do(
        lambda: threading.Thread(target=_run_weekly_stock_scan, daemon=True,
                                 name='weekly-stock-scan').start()
    )
    logger.info("Weekly stock scan scheduled: Saturday 01:00")

    while True:
        schedule.run_pending()
        time.sleep(20)


# REST API

@app.route('/')
def dashboard():
    return render_template('dashboard.html')


@app.route('/api/positions')
def api_positions():
    with _state_lock:
        return jsonify(dict(_state))


@app.route('/api/history/<symbol>')
def api_history(symbol):
    hours = int(request.args.get('hours', 24))
    return jsonify(get_price_history(symbol.upper(), hours=hours))


@app.route('/api/alerts')
def api_alerts():
    return jsonify(get_recent_alerts(limit=100))


@app.route('/api/symbols')
def api_symbols():
    return jsonify(get_tracked_symbols())


@app.route('/api/config', methods=['GET'])
def api_get_config():
    cfg  = load_config()
    safe = {k: v for k, v in cfg.items() if k != 'email'}
    safe['email_enabled'] = cfg.get('email', {}).get('enabled', False)
    safe['email_address'] = cfg.get('email', {}).get('to_address', '')
    return jsonify(safe)


@app.route('/api/config', methods=['POST'])
def api_save_config():
    data = request.get_json(force=True)
    cfg  = load_config()

    if 'tolerance_percent' in data:
        cfg['tolerance_percent'] = float(data['tolerance_percent'])
    if 'days_before_expiration_warning' in data:
        cfg['days_before_expiration_warning'] = int(data['days_before_expiration_warning'])
    if 'scan_interval_minutes' in data:
        cfg['scan_interval_minutes'] = max(1, int(data['scan_interval_minutes']))

    email = cfg.setdefault('email', {})
    if 'email_enabled' in data:
        email['enabled'] = bool(data['email_enabled'])
    if 'email_to_address' in data:
        addr = str(data['email_to_address']).strip()
        if addr:
            email['to_address'] = addr

    save_config(cfg)
    return jsonify({'success': True})


@app.route('/api/cash')
def api_cash():
    snapshots = get_cash_snapshots(days=14)
    live = None
    try:
        if _engine.client.ensure_logged_in():
            live = _engine.client.get_account_cash_info()
    except Exception:
        pass
    return jsonify({'snapshots': snapshots, 'live': live})


@app.route('/api/cash/snapshot', methods=['POST'])
def api_manual_snapshot():
    from database import log_cash_snapshot
    try:
        if not _engine.client.ensure_logged_in():
            return jsonify({'success': False, 'message': 'Not logged in to Robinhood'}), 401
        info = _engine.client.get_account_cash_info()
        if info:
            log_cash_snapshot('manual', **info)
            return jsonify({'success': True, 'data': info})
        return jsonify({'success': False, 'message': 'Could not fetch cash info'}), 500
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/scan', methods=['POST'])
def api_trigger_scan():
    t = threading.Thread(target=_run_scan, daemon=True)
    t.start()
    return jsonify({'success': True, 'message': 'Scan triggered'})


@app.route('/api/transfers')
def api_transfers():
    """Return all transfers + capital summary."""
    return jsonify({
        'transfers': get_transfers(),
        'summary':   get_capital_summary(),
    })


@app.route('/api/transfers/sync', methods=['POST'])
def api_sync_transfers():
    """Trigger a Robinhood bank-transfer sync and return updated data."""
    try:
        if not _engine.client.ensure_logged_in():
            return jsonify({'success': False, 'message': 'Not logged in'}), 401
        count = _engine.client.sync_transfers_to_db()
        return jsonify({
            'success':    True,
            'synced':     count,
            'transfers':  get_transfers(),
            'summary':    get_capital_summary(),
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/transfers/<int:transfer_id>/clear', methods=['POST'])
def api_clear_transfer(transfer_id):
    """Manually mark a pending transfer as cleared."""
    from database import update_transfer_status
    try:
        update_transfer_status(transfer_id, 'cleared')
        return jsonify({'success': True, 'transfers': get_transfers(), 'summary': get_capital_summary()})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/income')
def api_income():
    """Return WTD/MTD/YTD premium income summary + recent trades."""
    return jsonify({
        'summary':    get_income_summary(),
        'by_month':   get_income_by_month(months=12),
        'trades':     get_income_trades(limit=200),
        'by_symbol':  get_income_by_symbol(limit=20),
    })


@app.route('/api/income/sync', methods=['POST'])
def api_sync_income():
    """Pull all filled options orders from Robinhood and store them."""
    try:
        if not _engine.client.ensure_logged_in():
            return jsonify({'success': False, 'message': 'Not logged in'}), 401
        count = _engine.client.sync_options_income_to_db()
        return jsonify({
            'success':   True,
            'synced':    count,
            'summary':   get_income_summary(),
            'by_month':  get_income_by_month(months=12),
            'trades':    get_income_trades(limit=200),
            'by_symbol': get_income_by_symbol(limit=20),
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/transfers/<int:transfer_id>', methods=['DELETE'])
def api_delete_transfer(transfer_id):
    """Delete a manually-entered transfer row."""
    try:
        delete_transfer(transfer_id)
        return jsonify({'success': True, 'transfers': get_transfers(), 'summary': get_capital_summary()})
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.route('/api/auth/status')
def api_auth_status():
    """Return the current Robinhood auth state so the dashboard can react."""
    return jsonify(_engine.client.get_auth_state())


@app.route('/api/auth/mfa', methods=['POST'])
def api_auth_mfa():
    """Accept a user-supplied MFA code and complete the Robinhood login."""
    data = request.get_json(force=True) or {}
    code = str(data.get('code', '')).strip()
    if not code:
        return jsonify({'success': False, 'message': 'MFA code is required'}), 400
    ok = _engine.client.submit_mfa(code)
    state = _engine.client.get_auth_state()
    if ok:
        # Kick off a position scan now that we're authenticated
        import threading
        threading.Thread(target=_run_scan, daemon=True).start()
    return jsonify({'success': ok, **state})


@app.route('/api/auth/retry', methods=['POST'])
def api_auth_retry():
    """Trigger a fresh login attempt (e.g. after updating .env credentials)."""
    ok = _engine.client.retry_login()
    state = _engine.client.get_auth_state()
    if ok:
        import threading
        threading.Thread(target=_run_scan, daemon=True).start()
    return jsonify({'success': ok, **state})


# ── Stock Universe ────────────────────────────────────────────────────────────

_universe_scanner = None

@app.route('/api/stock-universe')
def api_stock_universe():
    """Return graded stocks from the local DB (no live API call)."""
    return jsonify(get_stock_universe(active_only=True))


@app.route('/api/stock-universe/stats')
def api_stock_universe_stats():
    return jsonify(get_stock_universe_stats())


@app.route('/api/stock-universe/scan', methods=['POST'])
def api_trigger_universe_scan():
    global _universe_scanner
    from stock_universe_scanner import StockUniverseScanner
    if _universe_scanner and _universe_scanner.progress.get('running'):
        return jsonify({'success': False, 'message': 'Scan already running'}), 409
    _universe_scanner = StockUniverseScanner()
    t = threading.Thread(target=_universe_scanner.run_full_scan, daemon=True, name='universe-scan')
    t.start()
    return jsonify({'success': True, 'message': 'Stock universe scan started'})


@app.route('/api/stock-universe/scan/status')
def api_universe_scan_status():
    global _universe_scanner
    if not _universe_scanner:
        return jsonify({'running': False, 'message': 'No scan started yet'})
    return jsonify(_universe_scanner.progress)


@app.route('/api/stock-universe/scan/stop', methods=['POST'])
def api_stop_universe_scan():
    global _universe_scanner
    if _universe_scanner:
        _universe_scanner._stop_event.set()
    return jsonify({'success': True})


# ── Stock Detail ──────────────────────────────────────────────────────────────

@app.route('/api/stock-detail/<symbol>')
def api_stock_detail(symbol):
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol.upper())
        info   = ticker.info or {}
        hist   = ticker.history(period='1mo', interval='1d')
        prices = []
        if not hist.empty:
            prices = [{'date': str(d.date()), 'close': round(float(c), 2)}
                      for d, c in zip(hist.index, hist['Close'])]
        return jsonify({
            'symbol':        symbol.upper(),
            'name':          info.get('shortName') or info.get('longName', ''),
            'current_price': info.get('currentPrice') or info.get('regularMarketPrice'),
            'market_cap':    info.get('marketCap'),
            'pe_ratio':      info.get('trailingPE'),
            'pb_ratio':      info.get('priceToBook'),
            'week_52_high':  info.get('fiftyTwoWeekHigh'),
            'week_52_low':   info.get('fiftyTwoWeekLow'),
            'prices':        prices,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500



# ── Covered Calls ─────────────────────────────────────────────────────────────

_cc_scanner = None

@app.route('/api/covered-calls')
def api_covered_calls():
    tier  = request.args.get('tier')
    grade = request.args.get('grade')
    return jsonify({
        'opportunities': get_covered_call_opportunities(tier=tier, grade=grade),
        'scan_time':     get_covered_call_scan_time(),
    })


@app.route('/api/covered-calls/scan', methods=['POST'])
def api_trigger_cc_scan():
    global _cc_scanner
    from covered_call_screener import CoveredCallScreener
    if _cc_scanner and _cc_scanner.progress.get('running'):
        return jsonify({'success': False, 'message': 'Scan already running'}), 409
    _cc_scanner = CoveredCallScreener()
    t = threading.Thread(target=_cc_scanner.run_scan, daemon=True, name='cc-scan')
    t.start()
    return jsonify({'success': True, 'message': 'Covered call scan started'})


@app.route('/api/covered-calls/scan/status')
def api_cc_scan_status():
    global _cc_scanner
    if not _cc_scanner:
        return jsonify({'running': False, 'message': 'No scan started yet'})
    return jsonify(_cc_scanner.progress)


@app.route('/api/covered-calls/scan/stop', methods=['POST'])
def api_stop_cc_scan():
    global _cc_scanner
    if _cc_scanner:
        _cc_scanner.progress['running'] = False
    return jsonify({'success': True})


# ── Put Spreads ───────────────────────────────────────────────────────────────

_put_scanner = None

@app.route('/api/put-spreads')
def api_put_spreads():
    tier  = request.args.get('tier')
    grade = request.args.get('grade')
    return jsonify({'opportunities': get_put_opportunities(tier=tier, grade=grade)})


@app.route('/api/put-spreads/scan', methods=['POST'])
def api_trigger_put_scan():
    global _put_scanner
    from put_screener import PutScreener
    if _put_scanner and _put_scanner.progress.get('running'):
        return jsonify({'success': False, 'message': 'Scan already running'}), 409
    _put_scanner = PutScreener()
    t = threading.Thread(target=_put_scanner.run_scan, daemon=True, name='put-scan')
    t.start()
    return jsonify({'success': True, 'message': 'Put spread scan started'})


@app.route('/api/put-spreads/scan/status')
def api_put_scan_status():
    global _put_scanner
    if not _put_scanner:
        return jsonify({'running': False, 'message': 'No scan started yet'})
    return jsonify(_put_scanner.progress)


@app.route('/api/put-spreads/scan/stop', methods=['POST'])
def api_stop_put_scan():
    global _put_scanner
    if _put_scanner:
        _put_scanner.progress['running'] = False
    return jsonify({'success': True})


# Entry point

if __name__ == '__main__':
    logger.info("=" * 60)
    logger.info("  Robinhood Options Monitor starting...")
    logger.info("=" * 60)

    init_db()
    seed_initial_transfers()
    prune_old_data(days=30)

    monitor_thread = threading.Thread(target=_background_monitor, daemon=True, name='monitor')
    monitor_thread.start()

    def _open_browser():
        time.sleep(2)
        webbrowser.open('http://localhost:5000')
    threading.Thread(target=_open_browser, daemon=True).start()

    logger.info("Dashboard -> http://localhost:5000")
    try:
        from waitress import serve
        logger.info("Starting production server via Waitress...")
        serve(app, host='0.0.0.0', port=5000, threads=4)
    except ImportError:
        logger.warning("waitress not installed – falling back to Flask dev server")
        logger.warning("Run: pip install waitress")
        app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
