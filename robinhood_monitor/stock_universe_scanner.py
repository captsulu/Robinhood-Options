"""
Stock Universe Scanner
======================
Downloads the full NYSE + Nasdaq stock list from the SEC EDGAR company-tickers
endpoint and runs a Benjamin Graham grade on every symbol, storing results in
the stock_universe table.

Designed to be called from app.py on a weekly schedule (typically overnight).
Rate-limited to ~1.5 s/stock so a full run of ~7,500 symbols takes roughly
3 hours — schedule for early Sunday morning.

Usage (directly):
    from stock_universe_scanner import StockUniverseScanner
    scanner = StockUniverseScanner()
    scanner.run_full_scan()
"""

import json
import logging
import threading
import time
import urllib.request
from datetime import datetime, timedelta

from database import upsert_stock_grade, set_all_stocks_inactive, get_stock_universe_stats
from stock_grader import grade_stock

logger = logging.getLogger(__name__)

# Public URL for the SEC EDGAR company-tickers-by-exchange file.
# Contains CIK, company name, ticker, and exchange for all SEC registrants.
SEC_TICKERS_URL = (
    'https://www.sec.gov/files/company_tickers_exchange.json'
)
SEC_USER_AGENT = 'RobinhoodMonitor/1.0 captsulu@gmail.com'

# Exchanges we want to scan (NYSE, Nasdaq).  OTC and CBOE are excluded.
TARGET_EXCHANGES = {'NYSE', 'Nasdaq'}

# Gap between yfinance requests.  Yahoo Finance rate-limits aggressively;
# 1.5 s is conservative enough to avoid 429 errors overnight.
REQUEST_DELAY_SECONDS = 1.5

# Minimum staleness before re-scanning a symbol.  If a stock was graded
# within the last RESCAN_AFTER_DAYS days it will be skipped on incremental runs.
RESCAN_AFTER_DAYS = 7


class StockUniverseScanner:
    """
    Orchestrates fetching a full NYSE/Nasdaq symbol list and grading each stock.
    Progress is reported via the shared ``_progress`` dict so the Flask app can
    serve it to the browser.
    """

    def __init__(self):
        self._stop_event = threading.Event()
        # Shared progress dict — read by /api/stock-universe/scan/status
        self.progress = {
            'running':   False,
            'total':     0,
            'done':      0,
            'errors':    0,
            'skipped':   0,
            'current':   '',
            'started_at': None,
            'finished_at': None,
            'message':   'Not started',
        }
        self._lock = threading.Lock()

    # ── Public API ───────────────────────────────────────────────────────────

    def run_full_scan(self, force_rescan: bool = False):
        """
        Full scan: fetch the stock list, mark all existing rows inactive,
        then grade every NYSE/Nasdaq stock.

        Args:
            force_rescan: If True, re-grade every symbol even if recently scanned.
        """
        with self._lock:
            if self.progress['running']:
                logger.info('Scan already running — skipping duplicate trigger')
                return
            self._stop_event.clear()
            self.progress.update({
                'running':    True,
                'done':       0,
                'errors':     0,
                'skipped':    0,
                'current':    '',
                'started_at': datetime.now().isoformat(),
                'finished_at': None,
                'message':    'Fetching stock list…',
            })

        try:
            symbols = self._fetch_stock_list()
            if not symbols:
                self._finish('Failed to fetch stock list')
                return

            with self._lock:
                self.progress['total'] = len(symbols)
                self.progress['message'] = f'Grading {len(symbols):,} stocks…'

            # Mark everything inactive so removed listings are detected
            set_all_stocks_inactive()

            self._grade_batch(symbols, force_rescan=force_rescan)
            stats = get_stock_universe_stats()
            self._finish(
                f"Done — {stats.get('total', 0):,} stocks graded. "
                f"Grade A: {stats.get('by_grade', {}).get('A', 0)}"
            )

        except Exception as exc:
            logger.error(f'StockUniverseScanner error: {exc}', exc_info=True)
            self._finish(f'Scan failed: {exc}')

    def stop(self):
        """Request a graceful stop of the running scan."""
        self._stop_event.set()

    # ── Private helpers ──────────────────────────────────────────────────────

    def _fetch_stock_list(self) -> list:
        """
        Download NYSE + Nasdaq tickers from SEC EDGAR.
        Returns a list of dicts: {symbol, company_name, exchange}.
        """
        logger.info('Downloading stock list from SEC EDGAR…')
        try:
            req = urllib.request.Request(
                SEC_TICKERS_URL,
                headers={'User-Agent': SEC_USER_AGENT}
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
        except Exception as exc:
            logger.error(f'Failed to download stock list: {exc}')
            return []

        fields = data.get('fields', [])
        rows   = data.get('data', [])

        try:
            i_ticker   = fields.index('ticker')
            i_name     = fields.index('name')
            i_exchange = fields.index('exchange')
        except ValueError:
            logger.error('Unexpected SEC EDGAR field layout')
            return []

        stocks = []
        for row in rows:
            exchange = row[i_exchange]
            if exchange not in TARGET_EXCHANGES:
                continue
            ticker = str(row[i_ticker]).strip().upper()
            if not ticker or len(ticker) > 10:
                continue
            # Skip preferred shares, warrants, rights (contain '+', '/', spaces)
            if any(c in ticker for c in ('+', '/', ' ')):
                continue
            stocks.append({
                'symbol':       ticker,
                'company_name': row[i_name],
                'exchange':     exchange,
            })

        logger.info(f'Stock list: {len(stocks):,} NYSE/Nasdaq symbols')
        return stocks

    def _grade_batch(self, symbols: list, force_rescan: bool = False):
        """Grade every symbol in the list, saving results to the DB."""
        stale_cutoff = (datetime.now() - timedelta(days=RESCAN_AFTER_DAYS)).isoformat()

        for i, stock in enumerate(symbols):
            if self._stop_event.is_set():
                logger.info('Scan stopped by user request')
                break

            sym      = stock['symbol']
            exchange = stock['exchange']
            name     = stock['company_name']

            with self._lock:
                self.progress['current'] = sym

            # Check if we can skip (already recently graded)
            if not force_rescan:
                from database import _connect
                conn = _connect()
                row = conn.execute(
                    'SELECT last_updated, grade FROM stock_universe WHERE symbol=?',
                    (sym,)
                ).fetchone()
                conn.close()
                if row and row[0] and row[0] > stale_cutoff and row[1]:
                    # Still fresh — just mark it active again and skip grading
                    from database import _connect
                    conn = _connect()
                    conn.execute(
                        'UPDATE stock_universe SET is_active=1 WHERE symbol=?', (sym,)
                    )
                    conn.commit()
                    conn.close()
                    with self._lock:
                        self.progress['skipped'] += 1
                        self.progress['done']    += 1
                    continue

            try:
                grade_data = grade_stock(sym)
                # Augment with exchange + company name from our list
                grade_data['exchange']     = exchange
                grade_data['company_name'] = grade_data.get('name') or name
                upsert_stock_grade(sym, grade_data)

                if grade_data.get('error'):
                    with self._lock:
                        self.progress['errors'] += 1
                else:
                    pass  # success

            except Exception as exc:
                logger.warning(f'Grade error {sym}: {exc}')
                upsert_stock_grade(sym, {
                    'exchange':     exchange,
                    'company_name': name,
                    'error':        str(exc),
                })
                with self._lock:
                    self.progress['errors'] += 1

            with self._lock:
                self.progress['done'] += 1
                if (i + 1) % 100 == 0:
                    pct = (i + 1) / len(symbols) * 100
                    logger.info(
                        f'Scan progress: {i+1}/{len(symbols)} ({pct:.1f}%) '
                        f'errors={self.progress["errors"]}'
                    )

            # Rate limiting — be polite to Yahoo Finance
            time.sleep(REQUEST_DELAY_SECONDS)

    def _finish(self, message: str):
        with self._lock:
            self.progress.update({
                'running':     False,
                'finished_at': datetime.now().isoformat(),
                'message':     message,
                'current':     '',
            })
        logger.info(f'StockUniverseScanner finished: {message}')
