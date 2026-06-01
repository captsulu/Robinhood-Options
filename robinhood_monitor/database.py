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

    # ── Stock Universe ────────────────────────────────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS stock_universe (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol           TEXT    NOT NULL UNIQUE,
            company_name     TEXT,
            exchange         TEXT,
            sector           TEXT,
            industry         TEXT,
            current_price    REAL,
            intrinsic_value  REAL,
            margin_of_safety REAL,
            grade            TEXT,
            score            REAL,
            pe_ratio         REAL,
            pb_ratio         REAL,
            eps_ttm          REAL,
            bvps             REAL,
            ttm_fcf          REAL,
            fcf_per_share    REAL,
            ath_52w          REAL,
            low_52w          REAL,
            pct_of_ath       REAL,
            has_options      INTEGER DEFAULT 0,
            is_active        INTEGER DEFAULT 1,
            last_updated     TEXT
        )
    ''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_universe_grade  ON stock_universe (grade)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_universe_active ON stock_universe (is_active)')

    # ── Covered Call Opportunities ─────────────────────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS covered_call_opportunities (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol           TEXT    NOT NULL,
            company_name     TEXT,
            grade            TEXT,
            current_price    REAL,
            expiration       TEXT,
            dte              INTEGER,
            strike           REAL,
            bid              REAL,
            ask              REAL,
            mid              REAL,
            delta            REAL,
            iv               REAL,
            otm_pct          REAL,
            credit           REAL,
            collateral       REAL,
            period_roc       REAL,
            annualized_roc   REAL,
            premium_per_share REAL,
            roi_pct          REAL,
            annualised_roi   REAL,
            tier             TEXT,
            criteria         TEXT,
            news_risk        TEXT,
            news_flag        TEXT,
            scanned_at       TEXT
        )
    ''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_cc_symbol ON covered_call_opportunities (symbol)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_cc_tier   ON covered_call_opportunities (tier)')

    # ── Put Opportunities ─────────────────────────────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS put_opportunities (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol           TEXT    NOT NULL,
            company_name     TEXT,
            grade            TEXT,
            current_price    REAL,
            expiration       TEXT,
            dte              INTEGER,
            strike           REAL,
            long_strike      REAL,
            bid              REAL,
            ask              REAL,
            mid              REAL,
            delta            REAL,
            iv               REAL,
            otm_pct          REAL,
            credit           REAL,
            collateral       REAL,
            period_roc       REAL,
            annualized_roc   REAL,
            max_profit       REAL,
            max_loss         REAL,
            roi_pct          REAL,
            annualised_roi   REAL,
            tier             TEXT,
            criteria         TEXT,
            news_risk        TEXT,
            news_flag        TEXT,
            scanned_at       TEXT
        )
    ''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_put_symbol ON put_opportunities (symbol)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_put_tier   ON put_opportunities (tier)')

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
    today = datetime.now().strftime('%Y-%m-%d')
    conn  = _connect()
    verb  = 'INSERT OR REPLACE' if snapshot_type in ('open', 'close') else 'INSERT'
    conn.execute(
        verb + ' INTO cash_snapshots '
        '(snapshot_type, date, timestamp, cash, cash_available_for_withdrawal, '
        'buying_power, cash_held_for_orders, uncleared_deposits, portfolio_equity) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (snapshot_type, today, datetime.now().isoformat(),
         cash, cash_available_for_withdrawal, buying_power,
         cash_held_for_orders, uncleared_deposits, portfolio_equity)
    )
    conn.commit()
    conn.close()


def get_cash_snapshots(days=14):
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    conn   = _connect()
    rows   = conn.execute(
        'SELECT snapshot_type, date, timestamp, cash, '
        'cash_available_for_withdrawal, buying_power, '
        'cash_held_for_orders, uncleared_deposits, portfolio_equity '
        'FROM cash_snapshots WHERE date >= ? ORDER BY date DESC, snapshot_type DESC',
        (cutoff,)
    ).fetchall()
    conn.close()
    cols = ['snapshot_type', 'date', 'timestamp', 'cash',
            'cash_available_for_withdrawal', 'buying_power',
            'cash_held_for_orders', 'uncleared_deposits', 'portfolio_equity']
    return [dict(zip(cols, r)) for r in rows]


def get_todays_snapshot_types():
    today = datetime.now().strftime('%Y-%m-%d')
    conn  = _connect()
    rows  = conn.execute('SELECT snapshot_type FROM cash_snapshots WHERE date = ?', (today,)).fetchall()
    conn.close()
    return {r[0] for r in rows}


# ── Transfers ─────────────────────────────────────────────────────────────────

def get_transfers():
    conn = _connect()
    rows = conn.execute(
        'SELECT id, rh_id, transfer_date, amount, direction, status, source, notes, created_at '
        'FROM transfers ORDER BY transfer_date DESC, id DESC'
    ).fetchall()
    conn.close()
    cols = ['id', 'rh_id', 'transfer_date', 'amount', 'direction', 'status', 'source', 'notes', 'created_at']
    return [dict(zip(cols, r)) for r in rows]


def get_capital_summary():
    conn = _connect()
    dep = conn.execute("SELECT COALESCE(SUM(amount),0) FROM transfers WHERE direction='deposit' AND status='cleared'").fetchone()[0]
    wdl = conn.execute("SELECT COALESCE(SUM(amount),0) FROM transfers WHERE direction='withdrawal' AND status='cleared'").fetchone()[0]
    pnd = conn.execute("SELECT COALESCE(SUM(amount),0) FROM transfers WHERE direction='deposit' AND status='pending'").fetchone()[0]
    conn.close()
    return {
        'total_deposited':  round(dep, 2),
        'total_withdrawn':  round(wdl, 2),
        'net_capital':      round(dep - wdl, 2),
        'pending_deposits': round(pnd, 2),
    }


def update_transfer_status(transfer_id, new_status):
    conn = _connect()
    conn.execute('UPDATE transfers SET status=? WHERE id=?', (new_status, transfer_id))
    conn.commit()
    conn.close()


def delete_transfer(transfer_id):
    conn = _connect()
    row = conn.execute("SELECT source FROM transfers WHERE id=?", (transfer_id,)).fetchone()
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
    conn = _connect()
    existing = conn.execute('SELECT id, status FROM transfers WHERE rh_id=?', (rh_id,)).fetchone()
    if existing:
        if existing[1] != status:
            conn.execute('UPDATE transfers SET status=? WHERE rh_id=?', (status, rh_id))
    else:
        conn.execute(
            "INSERT INTO transfers (rh_id, transfer_date, amount, direction, status, source, notes, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'robinhood', ?, ?)",
            (rh_id, transfer_date, amount, direction, status, notes, datetime.now().isoformat())
        )
    conn.commit()
    conn.close()


def prune_old_data(days=30):
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    conn = _connect()
    conn.execute('DELETE FROM price_history WHERE timestamp < ?', (cutoff,))
    conn.commit()
    conn.close()


# ── Stock Universe ────────────────────────────────────────────────────────────

def upsert_stock_grade(symbol, data):
    conn = _connect()
    now  = datetime.now().isoformat()
    conn.execute(
        'INSERT INTO stock_universe '
        '(symbol, company_name, exchange, sector, industry, current_price, '
        'intrinsic_value, margin_of_safety, grade, score, pe_ratio, pb_ratio, '
        'eps_ttm, bvps, ttm_fcf, fcf_per_share, ath_52w, low_52w, pct_of_ath, '
        'has_options, is_active, last_updated) '
        'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?) '
        'ON CONFLICT(symbol) DO UPDATE SET '
        'company_name=excluded.company_name, exchange=excluded.exchange, '
        'sector=excluded.sector, industry=excluded.industry, '
        'current_price=excluded.current_price, intrinsic_value=excluded.intrinsic_value, '
        'margin_of_safety=excluded.margin_of_safety, grade=excluded.grade, '
        'score=excluded.score, pe_ratio=excluded.pe_ratio, pb_ratio=excluded.pb_ratio, '
        'eps_ttm=excluded.eps_ttm, bvps=excluded.bvps, ttm_fcf=excluded.ttm_fcf, '
        'fcf_per_share=excluded.fcf_per_share, ath_52w=excluded.ath_52w, '
        'low_52w=excluded.low_52w, pct_of_ath=excluded.pct_of_ath, '
        'has_options=excluded.has_options, is_active=1, last_updated=excluded.last_updated',
        (symbol.upper(),
         data.get('name') or data.get('company_name', ''),
         data.get('exchange', ''), data.get('sector', ''), data.get('industry', ''),
         data.get('current_price'), data.get('intrinsic_value'), data.get('margin_of_safety'),
         data.get('grade'), data.get('score'), data.get('pe_ratio'), data.get('pb_ratio'),
         data.get('eps_ttm'), data.get('bvps'), data.get('ttm_fcf'), data.get('fcf_per_share'),
         data.get('ath_52w'), data.get('low_52w'), data.get('pct_of_ath'),
         1 if data.get('has_options') else 0, now)
    )
    conn.commit()
    conn.close()


def set_all_stocks_inactive():
    conn = _connect()
    conn.execute("UPDATE stock_universe SET is_active=0")
    conn.commit()
    conn.close()


def get_stock_universe(active_only=True, has_options_only=False, grade=None, limit=None):
    conn  = _connect()
    where = []
    args  = []
    if active_only:
        where.append("is_active=1")
    if has_options_only:
        where.append("has_options=1")
    if grade:
        where.append("grade=?")
        args.append(grade)
    sql = "SELECT * FROM stock_universe"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY CASE grade WHEN 'A' THEN 1 WHEN 'B' THEN 2 WHEN 'C' THEN 3 WHEN 'D' THEN 4 ELSE 5 END, score DESC"
    if limit:
        sql += " LIMIT " + str(int(limit))
    rows = conn.execute(sql, args).fetchall()
    cols = [d[0] for d in conn.execute("PRAGMA table_info(stock_universe)").fetchall()]
    conn.close()
    return [dict(zip(cols, r)) for r in rows]


def get_stock_universe_stats():
    conn = _connect()
    total    = conn.execute("SELECT COUNT(*) FROM stock_universe WHERE is_active=1").fetchone()[0]
    has_opts = conn.execute("SELECT COUNT(*) FROM stock_universe WHERE is_active=1 AND has_options=1").fetchone()[0]
    last     = conn.execute("SELECT MAX(last_updated) FROM stock_universe WHERE is_active=1").fetchone()[0]
    grades   = {}
    for g in ('A','B','C','D','F'):
        grades[f'grade_{g}'] = conn.execute(
            "SELECT COUNT(*) FROM stock_universe WHERE is_active=1 AND grade=?", (g,)
        ).fetchone()[0]
    conn.close()
    return {'total_active': total, 'has_options': has_opts, 'last_scan': last, **grades}


# ── Covered Call Opportunities ────────────────────────────────────────────────

def clear_covered_call_opportunities():
    conn = _connect()
    conn.execute("DELETE FROM covered_call_opportunities")
    conn.commit()
    conn.close()


def insert_covered_call_opportunity(opp):
    conn = _connect()
    conn.execute(
        'INSERT INTO covered_call_opportunities '
        '(symbol, company_name, grade, current_price, expiration, dte, strike, '
        'bid, ask, mid, delta, iv, otm_pct, credit, collateral, period_roc, '
        'annualized_roc, premium_per_share, roi_pct, annualised_roi, '
        'tier, criteria, news_risk, news_flag, scanned_at) '
        'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (opp.get('symbol'), opp.get('company_name'), opp.get('grade'), opp.get('current_price'),
         opp.get('expiration'), opp.get('dte'), opp.get('strike'),
         opp.get('bid'), opp.get('ask'), opp.get('mid'), opp.get('delta'), opp.get('iv'),
         opp.get('otm_pct'), opp.get('credit'), opp.get('collateral'),
         opp.get('period_roc'), opp.get('annualized_roc'),
         opp.get('premium_per_share'), opp.get('roi_pct'), opp.get('annualised_roi'),
         opp.get('tier'), opp.get('criteria'), opp.get('news_risk'), opp.get('news_flag'),
         opp.get('scanned_at'))
    )
    conn.commit()
    conn.close()


def get_covered_call_opportunities(tier=None, grade=None, limit=500):
    conn  = _connect()
    where = []
    args  = []
    if tier:  where.append("tier=?");  args.append(tier)
    if grade: where.append("grade=?"); args.append(grade)
    sql = "SELECT * FROM covered_call_opportunities"
    if where: sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY annualized_roc DESC LIMIT ?"
    args.append(limit)
    rows = conn.execute(sql, args).fetchall()
    cols = [d[0] for d in conn.execute("PRAGMA table_info(covered_call_opportunities)").fetchall()]
    conn.close()
    return [dict(zip(cols, r)) for r in rows]


def get_covered_call_scan_time():
    conn = _connect()
    row  = conn.execute("SELECT MAX(scanned_at) FROM covered_call_opportunities").fetchone()
    conn.close()
    return row[0] if row else None


# ── Put Opportunities ─────────────────────────────────────────────────────────

def clear_put_opportunities():
    conn = _connect()
    conn.execute("DELETE FROM put_opportunities")
    conn.commit()
    conn.close()


def insert_put_opportunity(opp):
    conn = _connect()
    conn.execute(
        'INSERT INTO put_opportunities '
        '(symbol, company_name, grade, current_price, expiration, dte, strike, '
        'long_strike, bid, ask, mid, delta, iv, otm_pct, credit, collateral, '
        'period_roc, annualized_roc, max_profit, max_loss, '
        'roi_pct, annualised_roi, tier, criteria, news_risk, news_flag, scanned_at) '
        'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (opp.get('symbol'), opp.get('company_name'), opp.get('grade'), opp.get('current_price'),
         opp.get('expiration'), opp.get('dte'), opp.get('strike'), opp.get('long_strike'),
         opp.get('bid'), opp.get('ask'), opp.get('mid'), opp.get('delta'), opp.get('iv'),
         opp.get('otm_pct'), opp.get('credit'), opp.get('collateral'),
         opp.get('period_roc'), opp.get('annualized_roc'),
         opp.get('max_profit'), opp.get('max_loss'),
         opp.get('roi_pct'), opp.get('annualised_roi'),
         opp.get('tier'), opp.get('criteria'), opp.get('news_risk'), opp.get('news_flag'),
         opp.get('scanned_at'))
    )
    conn.commit()
    conn.close()


def get_put_opportunities(tier=None, grade=None, limit=500):
    conn  = _connect()
    where = []
    args  = []
    if tier:  where.append("tier=?");  args.append(tier)
    if grade: where.append("grade=?"); args.append(grade)
    sql = "SELECT * FROM put_opportunities"
    if where: sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY annualized_roc DESC LIMIT ?"
    args.append(limit)
    rows = conn.execute(sql, args).fetchall()
    cols = [d[0] for d in conn.execute("PRAGMA table_info(put_opportunities)").fetchall()]
    conn.close()
    return [dict(zip(cols, r)) for r in rows]


# ── Options Income ────────────────────────────────────────────────────────────

def upsert_options_income(rh_order_id, symbol, option_type, strike_price,
                          expiration_date, opening_strategy, closing_strategy,
                          direction, quantity, processed_premium, net_premium,
                          order_date, state):
    conn = _connect()
    conn.execute(
        'INSERT OR IGNORE INTO options_income '
        '(rh_order_id, symbol, option_type, strike_price, expiration_date, '
        'opening_strategy, closing_strategy, direction, quantity, '
        'processed_premium, net_premium, order_date, state, created_at) '
        'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (rh_order_id, symbol.upper(), option_type, strike_price, expiration_date,
         opening_strategy, closing_strategy, direction, quantity,
         processed_premium, net_premium, order_date, state, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def get_income_summary():
    now         = datetime.now()
    today       = now.strftime('%Y-%m-%d')
    monday      = (now - timedelta(days=now.weekday())).strftime('%Y-%m-%d')
    month_start = now.strftime('%Y-%m-01')
    year_start  = now.strftime('%Y-01-01')
    conn = _connect()

    def _q(start):
        r = conn.execute(
            "SELECT COALESCE(SUM(net_premium),0), COUNT(*) FROM options_income "
            "WHERE order_date >= ? AND order_date <= ? AND state='filled'",
            (start, today)).fetchone()
        return {'total': round(r[0], 2), 'trades': r[1]}

    def _cr(start):
        r = conn.execute(
            "SELECT COALESCE(SUM(net_premium),0) FROM options_income "
            "WHERE order_date >= ? AND order_date <= ? AND state='filled' AND direction='credit'",
            (start, today)).fetchone()
        return round(r[0], 2)

    def _db(start):
        r = conn.execute(
            "SELECT COALESCE(SUM(ABS(net_premium)),0) FROM options_income "
            "WHERE order_date >= ? AND order_date <= ? AND state='filled' AND direction='debit'",
            (start, today)).fetchone()
        return round(r[0], 2)

    result = {
        'wtd': _q(monday), 'mtd': _q(month_start), 'ytd': _q(year_start),
        'wtd_credits': _cr(monday), 'mtd_credits': _cr(month_start), 'ytd_credits': _cr(year_start),
        'wtd_debits':  _db(monday), 'mtd_debits':  _db(month_start), 'ytd_debits':  _db(year_start),
    }
    conn.close()
    return result


def get_income_by_month(months=12):
    cutoff = (datetime.now() - timedelta(days=months * 31)).strftime('%Y-%m-%d')
    conn   = _connect()
    rows   = conn.execute(
        "SELECT strftime('%Y-%m', order_date) as month, "
        "COALESCE(SUM(CASE WHEN direction='credit' THEN net_premium ELSE 0 END),0) as credits, "
        "COALESCE(SUM(CASE WHEN direction='debit' THEN ABS(net_premium) ELSE 0 END),0) as debits, "
        "COALESCE(SUM(net_premium),0) as net "
        "FROM options_income WHERE order_date >= ? AND state='filled' "
        "GROUP BY month ORDER BY month", (cutoff,)
    ).fetchall()
    conn.close()
    return [{'month': r[0], 'credits': round(r[1],2), 'debits': round(r[2],2), 'net': round(r[3],2)} for r in rows]


def get_income_trades(limit=200):
    conn = _connect()
    rows = conn.execute(
        "SELECT rh_order_id, symbol, option_type, strike_price, expiration_date, "
        "opening_strategy, closing_strategy, direction, quantity, "
        "processed_premium, net_premium, order_date, state "
        "FROM options_income WHERE state='filled' ORDER BY order_date DESC, id DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    cols = ['rh_order_id','symbol','option_type','strike_price','expiration_date',
            'opening_strategy','closing_strategy','direction','quantity',
            'processed_premium','net_premium','order_date','state']
    return [dict(zip(cols, r)) for r in rows]


def get_income_by_symbol(limit=20):
    conn = _connect()
    rows = conn.execute(
        "SELECT symbol, COALESCE(SUM(net_premium),0) as net, COUNT(*) as trades "
        "FROM options_income WHERE state='filled' GROUP BY symbol ORDER BY net DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [{'symbol': r[0], 'net': round(r[1],2), 'trades': r[2]} for r in rows]
