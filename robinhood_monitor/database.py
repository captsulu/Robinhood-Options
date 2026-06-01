"""
SQLite database for logging stock prices, alerts, cash snapshots, and transfers.
The database file (monitor.db) is created automatically on first run.
"""

import sqlite3
import os
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'monitor.db')


def _connect():
    return sqlite3.connect(DB_PATH)


def init_db():
    """Create tables if they don't already exist."""
    conn = _connect()
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS price_history (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol    TEXT    NOT NULL,
            price     REAL    NOT NULL,
            timestamp TEXT    NOT NULL
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS alerts (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol        TEXT    NOT NULL,
            option_id     TEXT,
            alert_type    TEXT    NOT NULL,
            message       TEXT    NOT NULL,
            strike        REAL,
            current_price REAL,
            distance_pct  REAL,
            expiration    TEXT,
            dte           INTEGER,
            timestamp     TEXT    NOT NULL,
            acknowledged  INTEGER DEFAULT 0
        )
    ''')

    c.execute('CREATE INDEX IF NOT EXISTS idx_price_symbol ON price_history (symbol, timestamp)')

    c.execute('''
        CREATE TABLE IF NOT EXISTS cash_snapshots (
            id                          INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_type               TEXT    NOT NULL,
            date                        TEXT    NOT NULL,
            timestamp                   TEXT    NOT NULL,
            cash                        REAL,
            cash_available_for_withdrawal REAL,
            buying_power                REAL,
            cash_held_for_orders        REAL,
            uncleared_deposits          REAL,
            portfolio_equity            REAL
        )
    ''')
    c.execute('''
        CREATE UNIQUE INDEX IF NOT EXISTS idx_cash_open_close
        ON cash_snapshots (date, snapshot_type)
        WHERE snapshot_type IN ('open', 'close')
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS transfers (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            rh_id         TEXT,
            transfer_date TEXT    NOT NULL,
            amount        REAL    NOT NULL,
            direction     TEXT    NOT NULL,
            status        TEXT    NOT NULL,
            source        TEXT    DEFAULT 'manual',
            notes         TEXT,
            created_at    TEXT    NOT NULL
        )
    ''')
    c.execute(
        'CREATE UNIQUE INDEX IF NOT EXISTS idx_transfer_rh_id '
        'ON transfers (rh_id) WHERE rh_id IS NOT NULL'
    )

    # ── Options Income ────────────────────────────────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS options_income (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            rh_order_id      TEXT    UNIQUE NOT NULL,
            symbol           TEXT    NOT NULL,
            option_type      TEXT,
            strike_price     REAL,
            expiration_date  TEXT,
            opening_strategy TEXT,
            closing_strategy TEXT,
            direction        TEXT,
            quantity         REAL,
            processed_premium REAL,
            net_premium      REAL    NOT NULL,
            order_date       TEXT    NOT NULL,
            state            TEXT,
            created_at       TEXT    NOT NULL
        )
    ''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_income_date   ON options_income (order_date)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_income_symbol ON options_income (symbol)')

    conn.commit()
    conn.close()


def seed_initial_transfers():
    """
    Seed Greg's known historical deposits (idempotent).
    On first run inserts all four rows.
    On subsequent runs promotes the manual-pending-1700 entry to 'cleared'
    if the transfer has now gone through.
    """
    conn  = _connect()
    count = conn.execute('SELECT COUNT(*) FROM transfers').fetchone()[0]

    if count == 0:
        now   = datetime.now().isoformat()
        seeds = [
            ('manual-20260408-5',    '2026-04-08',    5.00, 'deposit', 'cleared', 'Initial deposit'),
            ('manual-20260409-2000', '2026-04-09', 2000.00, 'deposit', 'cleared', 'Deposit'),
            ('manual-20260413-450',  '2026-04-13',  450.00, 'deposit', 'cleared', 'Deposit'),
            ('manual-pending-1700',  '2026-05-07', 1700.00, 'deposit', 'cleared', 'Deposit – cleared 2026-05-07'),
        ]
        conn.executemany(
            "INSERT OR IGNORE INTO transfers "
            "(rh_id, transfer_date, amount, direction, status, source, notes, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'manual', ?, ?)",
            [(s[0], s[1], s[2], s[3], s[4], s[5], now) for s in seeds]
        )
    else:
        # Promote pending 1700 → cleared if not done yet
        conn.execute(
            "UPDATE transfers SET status='cleared', "
            "notes='Deposit - cleared 2026-05-07' "
            "WHERE rh_id='manual-pending-1700' AND status='pending'"
        )

    conn.commit()
    conn.close()


def log_price(symbol, price):
    """Insert a new price record for a symbol."""
    conn = _connect()
    conn.execute(
        'INSERT INTO price_history (symbol, price, timestamp) VALUES (?, ?, ?)',
        (symbol.upper(), price, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def log_alert(symbol, option_id, alert_type, message, strike, current_price,
              distance_pct, expiration, dte):
    """Insert a new alert record."""
    conn = _connect()
    conn.execute(
        '''INSERT INTO alerts
           (symbol, option_id, alert_type, message, strike, current_price,
            distance_pct, expiration, dte, timestamp)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (symbol.upper(), option_id, alert_type, message, strike, current_price,
         distance_pct, expiration, dte, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def get_price_history(symbol, hours=24):
    """Return list of {price, recorded_at} dicts for a symbol over the last N hours."""
    cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
    conn = _connect()
    rows = conn.execute(
        'SELECT price, timestamp FROM price_history '
        'WHERE symbol = ? AND timestamp > ? ORDER BY timestamp',
        (symbol.upper(), cutoff)
    ).fetchall()
    conn.close()
    return [{'price': r[0], 'recorded_at': r[1]} for r in rows]


def get_recent_alerts(limit=50):
    """Return the most recent alert records."""
    conn = _connect()
    rows = conn.execute(
        'SELECT * FROM alerts ORDER BY timestamp DESC LIMIT ?', (limit,)
    ).fetchall()
    conn.close()
    cols = ['id', 'symbol', 'option_id', 'alert_type', 'message', 'strike',
            'current_price', 'distance_pct', 'expiration', 'dte', 'timestamp', 'acknowledged']
    return [dict(zip(cols, r)) for r in rows]


def get_tracked_symbols():
    """Return all symbols that have price history."""
    conn = _connect()
    rows = conn.execute('SELECT DISTINCT symbol FROM price_history').fetchall()
    conn.close()
    return [r[0] for r in rows]


def log_cash_snapshot(snapshot_type, cash, cash_available_for_withdrawal,
                      buying_power, cash_held_for_orders,
                      uncleared_deposits, portfolio_equity, **kwargs):
    """
    Insert a cash snapshot.
    'open' and 'close' use INSERT OR REPLACE so they stay unique per day.
    'trade', 'manual', and 'periodic' always insert a new row.
    """
    today = datetime.now().strftime('%Y-%m-%d')
    conn  = _connect()
    verb  = 'INSERT OR REPLACE' if snapshot_type in ('open', 'close') else 'INSERT'
    conn.execute(
        '{} INTO cash_snapshots '
        '(snapshot_type, date, timestamp, cash, cash_available_for_withdrawal, '
        'buying_power, cash_held_for_orders, uncleared_deposits, portfolio_equity) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)'.format(verb),
        (snapshot_type, today, datetime.now().isoformat(),
         cash, cash_available_for_withdrawal,
         buying_power, cash_held_for_orders,
         uncleared_deposits, portfolio_equity)
    )
    conn.commit()
    conn.close()


def get_cash_snapshots(days=14):
    """Return cash snapshot rows for the last N days, newest first."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    conn   = _connect()
    rows   = conn.execute(
        'SELECT snapshot_type, date, timestamp, cash, '
        'cash_available_for_withdrawal, buying_power, '
        'cash_held_for_orders, uncleared_deposits, portfolio_equity '
        'FROM cash_snapshots WHERE date >= ? '
        'ORDER BY date DESC, snapshot_type DESC',
        (cutoff,)
    ).fetchall()
    conn.close()
    cols = ['snapshot_type', 'date', 'timestamp', 'cash',
            'cash_available_for_withdrawal', 'buying_power',
            'cash_held_for_orders', 'uncleared_deposits', 'portfolio_equity']
    return [dict(zip(cols, r)) for r in rows]


def get_todays_snapshot_types():
    """Return which snapshot types ('open', 'close') already exist for today."""
    today = datetime.now().strftime('%Y-%m-%d')
    conn  = _connect()
    rows  = conn.execute(
        'SELECT snapshot_type FROM cash_snapshots WHERE date = ?', (today,)
    ).fetchall()
    conn.close()
    return {r[0] for r in rows}


# ── Transfers ─────────────────────────────────────────────────────────────────

def get_transfers():
    """Return all transfers, newest first."""
    conn = _connect()
    rows = conn.execute(
        'SELECT id, rh_id, transfer_date, amount, direction, status, source, notes, created_at '
        'FROM transfers ORDER BY transfer_date DESC, id DESC'
    ).fetchall()
    conn.close()
    cols = ['id', 'rh_id', 'transfer_date', 'amount', 'direction',
            'status', 'source', 'notes', 'created_at']
    return [dict(zip(cols, r)) for r in rows]


def get_capital_summary():
    """
    Compute capital-in figures.

    Returns:
      total_deposited   – sum of cleared deposits
      total_withdrawn   – sum of cleared withdrawals
      net_capital       – deposited minus withdrawn
      pending_deposits  – sum of pending deposits (informational only)
    """
    conn = _connect()
    dep = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM transfers "
        "WHERE direction='deposit' AND status='cleared'"
    ).fetchone()[0]
    wdl = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM transfers "
        "WHERE direction='withdrawal' AND status='cleared'"
    ).fetchone()[0]
    pnd = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM transfers "
        "WHERE direction='deposit' AND status='pending'"
    ).fetchone()[0]
    conn.close()
    return {
        'total_deposited':  round(dep, 2),
        'total_withdrawn':  round(wdl, 2),
        'net_capital':      round(dep - wdl, 2),
        'pending_deposits': round(pnd, 2),
    }


def update_transfer_status(transfer_id, new_status):
    """Update the status of a transfer row by its integer id."""
    conn = _connect()
    conn.execute('UPDATE transfers SET status=? WHERE id=?', (new_status, transfer_id))
    conn.commit()
    conn.close()


def delete_transfer(transfer_id):
    """
    Delete a manually-entered transfer row.
    Raises ValueError if the row does not exist or is not a manual entry.
    Returns True on success.
    """
    conn = _connect()
    row = conn.execute(
        "SELECT source FROM transfers WHERE id=?", (transfer_id,)
    ).fetchone()
    if not row:
        conn.close()
        raise ValueError(f"Transfer {transfer_id} not found")
    if row[0] != 'manual':
        conn.close()
        raise ValueError("Only manual transfers can be deleted")
    conn.execute("DELETE FROM transfers WHERE id=?", (transfer_id,))
    conn.commit()
    conn.close()
    return True


def upsert_transfer_by_rhid(rh_id, transfer_date, amount, direction, status, notes=''):
    """
    Insert a Robinhood-sourced transfer, or update its status if it already exists.
    Called during the Robinhood sync.
    """
    conn = _connect()
    existing = conn.execute(
        'SELECT id, status FROM transfers WHERE rh_id=?', (rh_id,)
    ).fetchone()
    if existing:
        if existing[1] != status:
            conn.execute('UPDATE transfers SET status=? WHERE rh_id=?', (status, rh_id))
    else:
        conn.execute(
            "INSERT INTO transfers "
            "(rh_id, transfer_date, amount, direction, status, source, notes, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'robinhood', ?, ?)",
            (rh_id, transfer_date, amount, direction, status, notes,
             datetime.now().isoformat())
        )
    conn.commit()
    conn.close()


def prune_old_data(days=30):
    """Delete price history older than N days to keep the DB small."""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    conn = _connect()
    conn.execute('DELETE FROM price_history WHERE timestamp < ?', (cutoff,))
    conn.commit()
    conn.close()


# ── Options Income ────────────────────────────────────────────────────────────

def upsert_options_income(rh_order_id, symbol, option_type, strike_price,
                          expiration_date, opening_strategy, closing_strategy,
                          direction, quantity, processed_premium, net_premium,
                          order_date, state):
    """Insert a filled options order, or skip if already recorded."""
    conn = _connect()
    conn.execute(
        '''INSERT OR IGNORE INTO options_income
           (rh_order_id, symbol, option_type, strike_price, expiration_date,
            opening_strategy, closing_strategy, direction, quantity,
            processed_premium, net_premium, order_date, state, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (rh_order_id, symbol.upper(), option_type, strike_price, expiration_date,
         opening_strategy, closing_strategy, direction, quantity,
         processed_premium, net_premium, order_date, state,
         datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def get_income_summary():
    """
    Return WTD / MTD / YTD net premium totals and trade counts.
    Only counts filled, credit + debit orders (net_premium can be negative for buy-backs).
    """
    now   = datetime.now()
    today = now.strftime('%Y-%m-%d')

    # Start of current ISO week (Monday)
    monday = (now - timedelta(days=now.weekday())).strftime('%Y-%m-%d')
    # Start of current month
    month_start = now.strftime('%Y-%m-01')
    # Start of current year
    year_start  = now.strftime('%Y-01-01')

    conn = _connect()

    def _query(start):
        row = conn.execute(
            "SELECT COALESCE(SUM(net_premium),0), COUNT(*) "
            "FROM options_income WHERE order_date >= ? AND order_date <= ? AND state='filled'",
            (start, today)
        ).fetchone()
        return {'total': round(row[0], 2), 'trades': row[1]}

    def _credits(start):
        row = conn.execute(
            "SELECT COALESCE(SUM(net_premium),0), COUNT(*) "
            "FROM options_income WHERE order_date >= ? AND order_date <= ? "
            "AND state='filled' AND direction='credit'",
            (start, today)
        ).fetchone()
        return {'total': round(row[0], 2), 'trades': row[1]}

    def _debits(start):
        row = conn.execute(
            "SELECT COALESCE(SUM(ABS(net_premium)),0) "
            "FROM options_income WHERE order_date >= ? AND order_date <= ? "
            "AND state='filled' AND direction='debit'",
            (start, today)
        ).fetchone()
        return round(row[0], 2)

    result = {
        'wtd':  _query(monday),
        'mtd':  _query(month_start),
        'ytd':  _query(year_start),
        'wtd_credits':  _credits(monday)['total'],
        'mtd_credits':  _credits(month_start)['total'],
        'ytd_credits':  _credits(year_start)['total'],
        'wtd_debits':   _debits(monday),
        'mtd_debits':   _debits(month_start),
        'ytd_debits':   _debits(year_start),
    }
    conn.close()
    return result


def get_income_by_month(months=12):
    """Return monthly net_premium totals for the last N months."""
    from datetime import date
    cutoff = (datetime.now() - timedelta(days=months * 31)).strftime('%Y-%m-%d')
    conn   = _connect()
    rows   = conn.execute(
        "SELECT strftime('%Y-%m', order_date) as month, "
        "  COALESCE(SUM(CASE WHEN direction='credit' THEN net_premium ELSE 0 END), 0) as credits, "
        "  COALESCE(SUM(CASE WHEN direction='debit'  THEN ABS(net_premium) ELSE 0 END), 0) as debits, "
        "  COALESCE(SUM(net_premium), 0) as net "
        "FROM options_income "
        "WHERE order_date >= ? AND state='filled' "
        "GROUP BY month ORDER BY month",
        (cutoff,)
    ).fetchall()
    conn.close()
    return [{'month': r[0], 'credits': round(r[1], 2),
             'debits': round(r[2], 2), 'net': round(r[3], 2)} for r in rows]


def get_income_trades(limit=200):
    """Return recent filled options income trades, newest first."""
    conn = _connect()
    rows = conn.execute(
        "SELECT rh_order_id, symbol, option_type, strike_price, expiration_date, "
        "  opening_strategy, closing_strategy, direction, quantity, "
        "  processed_premium, net_premium, order_date, state "
        "FROM options_income WHERE state='filled' "
        "ORDER BY order_date DESC, id DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    cols = ['rh_order_id', 'symbol', 'option_type', 'strike_price', 'expiration_date',
            'opening_strategy', 'closing_strategy', 'direction', 'quantity',
            'processed_premium', 'net_premium', 'order_date', 'state']
    return [dict(zip(cols, r)) for r in rows]


def get_income_by_symbol(limit=20):
    """Return net premium grouped by symbol, best performers first."""
    conn = _connect()
    rows = conn.execute(
        "SELECT symbol, "
        "  COALESCE(SUM(net_premium), 0) as net, "
        "  COUNT(*) as trades "
        "FROM options_income WHERE state='filled' "
        "GROUP BY symbol ORDER BY net DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [{'symbol': r[0], 'net': round(r[1], 2), 'trades': r[2]} for r in rows]
