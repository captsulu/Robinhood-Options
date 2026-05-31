"""
put_screener.py
Screens the stock universe for bull-put-spread opportunities that meet:

  Criteria (user-configurable at top):
    - Short put at 18–28 % OTM  (centred on the 20 % target)
    - |Delta| ≤ 0.20  (Black-Scholes, stdlib only — no scipy)
    - DTE 21 – 60
    - Spread collateral $100 – $500
    - Annualised ROI ≥ 20 %

  Tiers (by annualised ROI):
    Legendary  ≥ 40 %
    Epic       30 – 39 %
    Rare       25 – 29 %
    Good       20 – 24 %

  News / event risk:
    HIGH   — earnings date falls inside the option window, or a high-impact
             headline was found in the last 48 h (FDA, merger, bankruptcy …)
    MEDIUM — moderate-impact headline detected (lawsuit, downgrade, CEO change …)
    LOW    — nothing flagged
"""

from __future__ import annotations

import math
import time
import logging
import threading
from datetime import date, datetime

import yfinance as yf

from database import (
    get_stock_universe,
    clear_put_opportunities,
    insert_put_opportunity,
)

log = logging.getLogger(__name__)

# ── Scan parameters ────────────────────────────────────────────────────────
RISK_FREE_RATE    = 0.045        # approx US 3-month T-bill; update periodically
MIN_DTE, MAX_DTE  = 21, 60
OTM_LOW           = 0.18         # accept short puts 18 – 28 % OTM
OTM_HIGH          = 0.28
MAX_DELTA         = 0.20
MIN_COLLATERAL    = 100
MAX_COLLATERAL    = 500
MIN_ANN_ROI       = 0.20         # 20 % annualised
TOP_CANDIDATES    = 500          # stocks pulled from universe (sorted by score)
REQUEST_DELAY     = 0.75         # seconds between yfinance calls
NEWS_MAX_AGE_H    = 48           # hours of recency for news check

# Keywords that indicate HIGH price-movement risk
_HIGH_RISK_KW = [
    'earnings', 'fda approval', 'fda reject', 'fda decision', 'fda action',
    'fda approv', 'pdufa', 'nda submit', 'bla submit', 'clinical trial',
    'phase 3', 'phase 2', 'phase iii', 'phase ii',
    'merger', 'acquisition', 'acquired by', 'takeover', 'tender offer',
    'buyout', 'going private',
    'bankruptcy', 'chapter 11', 'chapter 7', 'default',
    'delist', 'sec investigation', 'sec charges', 'securities fraud',
    'guidance cut', 'lowered guidance', 'profit warning', 'revenue warning',
    'restatement', 'material weakness',
    'recall', 'complete response letter', 'crl',
]

# Keywords that indicate MEDIUM risk
_MED_RISK_KW = [
    'lawsuit', 'class action', 'downgrade', 'price target cut',
    'layoff', 'job cut', 'restructur', 'ceo resign', 'cfo resign',
    'ceo appoint', 'settlement', 'regulatory fine', 'penalty',
    'data breach', 'cybersecurity incident',
]


# ── Tier helper ────────────────────────────────────────────────────────────
def _tier(ann_roi_pct: float) -> str:
    if ann_roi_pct >= 40:
        return 'legendary'
    if ann_roi_pct >= 30:
        return 'epic'
    if ann_roi_pct >= 25:
        return 'rare'
    return 'good'


# ── Black-Scholes helpers (stdlib only) ───────────────────────────────────
def _ncdf(x: float) -> float:
    """Standard-normal CDF via math.erf — no scipy required."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _put_delta(S: float, K: float, r: float, iv: float, T: float) -> float | None:
    """Black-Scholes delta for a European put.  Returns a value in (-1, 0)."""
    try:
        if T <= 0 or iv <= 0:
            return -1.0 if K > S else 0.0
        d1 = (math.log(S / K) + (r + 0.5 * iv ** 2) * T) / (iv * math.sqrt(T))
        return _ncdf(d1) - 1.0
    except Exception:
        return None


def _put_price(S: float, K: float, r: float, iv: float, T: float) -> float | None:
    """Black-Scholes price for a European put."""
    try:
        if T <= 0:
            return max(0.0, K - S)
        if iv <= 0:
            return 0.0
        d1 = (math.log(S / K) + (r + 0.5 * iv ** 2) * T) / (iv * math.sqrt(T))
        d2 = d1 - iv * math.sqrt(T)
        return K * math.exp(-r * T) * _ncdf(-d2) - S * _ncdf(-d1)
    except Exception:
        return None


# ── News / event-risk helpers ──────────────────────────────────────────────
def _check_news_risk(ticker: yf.Ticker, max_dte: int) -> tuple[str, str]:
    """
    Returns (risk_level, flag_reason).
    risk_level: 'high' | 'medium' | 'low'
    flag_reason: human-readable explanation, e.g. "Earnings in 14d"
    """
    # 1. Upcoming earnings inside the option window
    try:
        cal = ticker.calendar
        if cal is not None and not cal.empty:
            earn_key = None
            for key in ('Earnings Date', 'earnings_date', 'Earnings date'):
                if key in cal.index:
                    earn_key = key
                    break
            if earn_key:
                earn_dates = cal.loc[earn_key]
                if hasattr(earn_dates, '__iter__'):
                    dates_list = list(earn_dates)
                else:
                    dates_list = [earn_dates]
                for d in dates_list:
                    try:
                        d_date = d.date() if hasattr(d, 'date') else d
                        days = (d_date - date.today()).days
                        if 0 <= days <= max_dte:
                            return 'high', f'Earnings in {days}d'
                    except Exception:
                        pass
    except Exception:
        pass

    # 2. Recent news headlines
    try:
        news_items = ticker.news or []
        cutoff_ts  = time.time() - NEWS_MAX_AGE_H * 3600
        for article in news_items[:15]:
            pub_ts = article.get('providerPublishTime', 0)
            if pub_ts < cutoff_ts:
                continue
            title = article.get('title', '').lower()
            for kw in _HIGH_RISK_KW:
                if kw in title:
                    return 'high', f'News: "{kw}"'
            for kw in _MED_RISK_KW:
                if kw in title:
                    return 'medium', f'News: "{kw}"'
    except Exception:
        pass

    return 'low', ''


# ── Main screener class ────────────────────────────────────────────────────
class PutScreener:

    def __init__(self):
        self.progress: dict = {
            'running':     False,
            'done':        0,
            'total':       0,
            'current':     '',
            'found':       0,
            'finished_at': None,
        }
        self._stop = False

    # ── Public API ─────────────────────────────────────────────────────

    def stop(self) -> None:
        self._stop = True

    def run_scan(self, grades: list[str] | None = None) -> tuple[bool, str]:
        """Start a background scan.  Returns (ok, message)."""
        if self.progress['running']:
            return False, 'Scan already in progress'

        grades = grades or ['A', 'B']
        self._stop = False

        result     = get_stock_universe(
            grades=grades,
            per_page=TOP_CANDIDATES,
            page=1,
            sort_by='score',
            sort_dir='desc',
        )
        candidates = result.get('stocks', [])
        if not candidates:
            return False, (
                'No graded stocks in the universe — '
                'run a Stock Screen scan first'
            )

        self.progress.update({
            'running': True, 'done': 0, 'total': len(candidates),
            'current': '', 'found': 0, 'finished_at': None,
        })
        threading.Thread(
            target=self._scan_thread, args=(candidates,), daemon=True
        ).start()
        return True, f'Scanning {len(candidates)} stocks…'

    # ── Internal ────────────────────────────────────────────────────────

    def _scan_thread(self, candidates: list[dict]) -> None:
        clear_put_opportunities()
        found      = 0
        scanned_at = datetime.utcnow().isoformat()

        for i, stock in enumerate(candidates):
            if self._stop:
                break
            sym = stock['symbol']
            self.progress.update({'current': sym, 'done': i, 'found': found})

            try:
                opps = self._scan_symbol(stock, scanned_at)
                for opp in opps:
                    try:
                        insert_put_opportunity(opp)
                        found += 1
                    except Exception as exc:
                        log.debug('insert %s: %s', sym, exc)
            except Exception as exc:
                log.warning('scan %s: %s', sym, exc)

            time.sleep(REQUEST_DELAY)

        self.progress.update({
            'running':     False,
            'done':        len(candidates),
            'found':       found,
            'finished_at': scanned_at,
        })

    def _scan_symbol(self, stock: dict, scanned_at: str) -> list[dict]:
        sym          = stock['symbol']
        price        = stock.get('current_price') or 0
        if price <= 0:
            return []

        grade        = stock.get('grade', '')
        company_name = stock.get('company_name', '')
        ticker       = yf.Ticker(sym)
        today        = date.today()
        opps: list[dict] = []

        # ── 1. Get available expirations ─────────────────────────────
        try:
            expirations = ticker.options
        except Exception:
            return []
        if not expirations:
            return []

        # ── 2. Scan each expiration in the DTE window ────────────────
        max_dte_found = 0
        for exp_str in expirations:
            try:
                exp_date = datetime.strptime(exp_str, '%Y-%m-%d').date()
            except ValueError:
                continue
            dte = (exp_date - today).days
            if not (MIN_DTE <= dte <= MAX_DTE):
                continue
            max_dte_found = max(max_dte_found, dte)

            try:
                chain = ticker.option_chain(exp_str)
                puts  = chain.puts
            except Exception:
                time.sleep(0.25)
                continue
            if puts is None or puts.empty:
                continue

            T = dte / 365.0

            # ── 3. Short-put candidates near 20 % OTM ─────────────────
            for _, srow in puts.iterrows():
                s_strike = float(srow['strike'])
                otm_frac = (price - s_strike) / price
                if not (OTM_LOW <= otm_frac <= OTM_HIGH):
                    continue

                iv  = float(srow.get('impliedVolatility') or 0)
                bid = float(srow.get('bid') or 0)
                ask = float(srow.get('ask') or 0)
                oi  = int(srow.get('openInterest') or 0)

                # Liquidity guards
                if iv <= 0 or bid <= 0 or ask <= 0 or oi < 5:
                    continue
                if (ask - bid) > 0.50 * ask:     # bid-ask > 50 % of ask → illiquid
                    continue

                s_mid = (bid + ask) / 2.0
                delta = _put_delta(price, s_strike, RISK_FREE_RATE, iv, T)
                if delta is None or abs(delta) > MAX_DELTA:
                    continue

                # ── 4. Long-put candidates in $1 – $5 range below ────
                lo          = s_strike - MAX_COLLATERAL / 100   # strike – 5
                hi          = s_strike - MIN_COLLATERAL / 100   # strike – 1
                long_cands  = puts[
                    (puts['strike'] >= lo) & (puts['strike'] < s_strike)
                ]

                for _, lrow in long_cands.iterrows():
                    l_strike     = float(lrow['strike'])
                    spread_width = round(s_strike - l_strike, 4)
                    collateral   = round(spread_width * 100, 2)
                    if not (MIN_COLLATERAL <= collateral <= MAX_COLLATERAL):
                        continue

                    l_bid = float(lrow.get('bid') or 0)
                    l_ask = float(lrow.get('ask') or 0)
                    l_iv  = float(lrow.get('impliedVolatility') or iv)

                    if l_bid > 0 and l_ask > 0:
                        l_mid = (l_bid + l_ask) / 2.0
                    else:
                        l_mid = _put_price(
                            price, l_strike, RISK_FREE_RATE, l_iv or iv, T
                        ) or 0.0

                    net = round(s_mid - l_mid, 4)
                    if net < 0.01:
                        continue

                    roi_period   = net / spread_width
                    ann_roi      = roi_period * (365.0 / dte)
                    if ann_roi < MIN_ANN_ROI:
                        continue

                    ann_roi_pct = round(ann_roi * 100, 2)

                    opps.append({
                        'symbol':        sym,
                        'company_name':  company_name,
                        'grade':         grade,
                        'current_price': price,
                        'expiration':    exp_str,
                        'dte':           dte,
                        'short_strike':  s_strike,
                        'long_strike':   l_strike,
                        'spread_width':  spread_width,
                        'collateral':    collateral,
                        'short_mid':     round(s_mid, 4),
                        'long_mid':      round(l_mid, 4),
                        'net_premium':   net,
                        'iv':            round(iv * 100, 2),   # stored as %
                        'delta':         round(abs(delta), 4),
                        'roi_pct':       round(roi_period * 100, 2),
                        'annualised_roi': ann_roi_pct,
                        'otm_pct':       round(otm_frac * 100, 2),
                        'tier':          _tier(ann_roi_pct),
                        # news_risk / news_flag filled in below
                        'news_risk':     'low',
                        'news_flag':     '',
                        'scanned_at':    scanned_at,
                    })

        # ── 5. News / earnings check (only if we have candidates) ────
        if opps and max_dte_found > 0:
            try:
                news_risk, news_flag = _check_news_risk(ticker, max_dte_found)
                for opp in opps:
                    opp['news_risk'] = news_risk
                    opp['news_flag'] = news_flag
            except Exception:
                pass

        return opps
