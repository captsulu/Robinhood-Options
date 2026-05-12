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
                      get_transfers, get_capital_summary, seed_initial_transfers)
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


def _background_monitor():
    config   = load_config()
    interval = max(1, config.get('scan_interval_minutes', 5))
    logger.info(f"Background monitor started - scanning every {interval} min")
    _run_scan()
    schedule.every(interval).minutes.do(_run_scan)
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
