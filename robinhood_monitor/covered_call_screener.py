"""
covered_call_screener.py
Screens the stock universe for covered-call opportunities across three criteria:

  Criteria:
    delta20 — Call delta 0.15–0.20, premium > $0.20/share, DTE 21–30
    otm20   — Call 20%+ OTM (strike >= 120% of price), ann. ROI >= 20%, DTE 21–60
    cheap   — Stock price <= $10, bid > $0.10/share, ann. ROI >= 15%, DTE 21–60

  All criteria enforce: strike > current_price  AND  delta <= 0.20

  Tiers (by annualised ROI):
    Legendary >= 40%   Epic 30–39%   Rare 25–29%   Good 20–24%   Other < 20%
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
    clear_covered_call_opportunities,
    insert_covered_call_opportunity,
)

log = logging.getLogger(__name__)

# ── Scan parameters ────────────────────────────────────────────────────────
RISK_FREE_RATE       = 0.045

# Global delta cap applied to ALL criteria
MAX_DELTA            = 0.20

# delta20 criteria
D20_MIN_DTE          = 21
D20_MAX_DTE          = 30
D20_MIN_DELTA        = 0.10
D20_MAX_DELTA        = 0.20
D20_MIN_PREMIUM      = 0.20   # $ per share

# otm20 criteria
OTM20_MIN_DTE        = 21
OTM20_MAX_DTE        = 60
OTM20_MIN_OTM_PCT    = 0.20   # strike at least 20% above price
OTM20_MIN_ANN_ROI    = 0.20

# cheap criteria
CHEAP_MAX_PRICE      = 10.00
CHEAP_MIN_DTE        = 21
CHEAP_MAX_DTE        = 60
CHEAP_MIN_PREMIUM    = 0.10
CHEAP_MIN_ANN_ROI    = 0.15

TOP_CANDIDATES       = 500
REQUEST_DELAY        = 0.75
NEWS_MAX_AGE_H       = 48

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
_MED_RISK_KW = [
    'lawsuit', 'class action', 'downgrade', 'price target cut',
    'layoff', 'job cut', 'restructur', 'ceo resign', 'cfo resign',
    'ceo appoint', 'settlement', 'regulatory fine', 'penalty',
    'data breach', 'cybersecurity incident',
]


# ── Helpers ────────────────────────────────────────────────────────────────

def _tier(ann_roi_pct: float) -> str:
    if ann_roi_pct >= 40: return 'legendary'
    if ann_roi_pct >= 30: return 'epic'
    if ann_roi_pct >= 25: return 'rare'
    if ann_roi_pct >= 20: return 'good'
    return 'other'


def _ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _call_delta(S: float, K: float, r: float, iv: float, T: float) -> float | None:
    """Black-Scholes delta for a European call.  Returns value in (0, 1)."""
    try:
        if T <= 0 or iv <= 0:
            return 1.0 if S > K else 0.0
        d1 = (math.log(S / K) + (r + 0.5 * iv ** 2) * T) / (iv * math.sqrt(T))
        return _ncdf(d1)
    except Exception:
        return None


def _ann_roi(premium: float, price: float, dte: int) -> float:
    """Annualised ROI for a covered call: premium / cost_basis x 365/DTE."""
    cost_basis = price - premium
    if cost_basis <= 0 or dte <= 0:
        return 0.0
    return (premium / cost_basis) * (365.0 / dte)


def _check_news_risk(ticker: yf.Ticker, max_dte: int):
    try:
        cal = ticker.calendar
        if cal is not None and not cal.empty:
            for key in ('Earnings Date', 'earnings_date', 'Earnings date'):
                if key in cal.index:
                    earn_dates = cal.loc[key]
                    dates_list = list(earn_dates) if hasattr(earn_dates, '__iter__') else [earn_dates]
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

    try:
        cutoff_ts = time.time() - NEWS_MAX_AGE_H * 3600
        for article in (ticker.news or [])[:15]:
            if article.get('providerPublishTime', 0) < cutoff_ts:
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

class CoveredCallScreener:

    def __init__(self):
        self.progress: dict = {
            'running':     False,
            'done':        0,
            'total':       0,
            'current':     '',
            'found':       0,
            'finished_at': None,
            'message':     'Not started',
        }
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run_scan(self, grades: list[str] | None = None) -> tuple[bool, str]:
        if self.progress['running']:
            return False, 'Scan already in progress'

        grades = grades or ['A', 'B']
        self._stop = False

        result = get_stock_universe(
            grades=grades,
            per_page=TOP_CANDIDATES,
            page=1,
            sort_by='score',
            sort_dir='desc',
            has_options_only=True,
        )
        candidates = result.get('stocks', [])
        if not candidates:
            return False, 'No graded stocks in the universe — run a Stock Screen scan first'

        self.progress.update({
            'running': True, 'done': 0, 'total': len(candidates),
            'current': '', 'found': 0, 'finished_at': None,
            'message': f'Scanning {len(candidates)} stocks…',
        })
        threading.Thread(target=self._scan_thread, args=(candidates,), daemon=True).start()
        return True, f'Scanning {len(candidates)} stocks…'

    def _scan_thread(self, candidates: list[dict]) -> None:
        clear_covered_call_opportunities()
        found = 0
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
                        insert_covered_call_opportunity(opp)
                        found += 1
                    except Exception as exc:
                        log.debug('CC insert %s: %s', sym, exc)
            except Exception as exc:
                log.warning('CC scan %s: %s', sym, exc)

            time.sleep(REQUEST_DELAY)

        self.progress.update({
            'running': False, 'done': len(candidates),
            'found': found, 'finished_at': scanned_at,
            'message': f'Done — {found} opportunities found',
        })

    def _scan_symbol(self, stock: dict, scanned_at: str) -> list[dict]:
        sym   = stock['symbol']
        price = stock.get('current_price') or 0
        if price <= 0:
            return []

        grade        = stock.get('grade', '')
        company_name = stock.get('company_name', '')
        ticker       = yf.Ticker(sym)
        today        = date.today()
        opps: list[dict] = []

        try:
            expirations = ticker.options
        except Exception:
            return []
        if not expirations:
            return []

        max_dte_seen = 0

        for exp_str in expirations:
            try:
                exp_date = datetime.strptime(exp_str, '%Y-%m-%d').date()
            except ValueError:
                continue
            dte = (exp_date - today).days

            # Only fetch chains within the widest window we care about
            if not (21 <= dte <= 60):
                continue
            max_dte_seen = max(max_dte_seen, dte)

            try:
                chain = ticker.option_chain(exp_str)
                calls = chain.calls
            except Exception:
                time.sleep(0.25)
                continue
            if calls is None or calls.empty:
                continue

            T = dte / 365.0

            for _, row in calls.iterrows():
                strike = float(row['strike'])
                iv     = float(row.get('impliedVolatility') or 0)
                bid    = float(row.get('bid') or 0)
                ask    = float(row.get('ask') or 0)
                oi     = int(row.get('openInterest') or 0)

                # ── Global hard filters ───────────────────────────────
                # Must be OTM (strike strictly above current price)
                if strike <= price:
                    continue
                if iv <= 0 or bid <= 0 or ask <= 0 or oi < 5:
                    continue
                if (ask - bid) > 0.50 * ask:   # too wide spread
                    continue

                mid       = (bid + ask) / 2.0
                otm_frac  = (strike - price) / price
                delta     = _call_delta(price, strike, RISK_FREE_RATE, iv, T)
                ann_roi   = _ann_roi(mid, price, dte)
                ann_roi_pct = round(ann_roi * 100, 2)

                # ── Global delta cap: all criteria must be <= 20% ─────
                if delta is None or delta > MAX_DELTA:
                    continue

                base = {
                    'symbol':            sym,
                    'company_name':      company_name,
                    'grade':             grade,
                    'current_price':     price,
                    'expiration':        exp_str,
                    'dte':               dte,
                    'strike':            strike,
                    'bid':               round(bid, 4),
                    'ask':               round(ask, 4),
                    'mid':               round(mid, 4),
                    'delta':             round(delta, 4),
                    'iv':                round(iv * 100, 2),
                    'otm_pct':           round(otm_frac * 100, 2),
                    'premium_per_share': round(mid, 4),
                    'roi_pct':           round(mid / price * 100, 2),
                    'annualised_roi':    ann_roi_pct,
                    'tier':              _tier(ann_roi_pct),
                    'news_risk':         'low',
                    'news_flag':         '',
                    'scanned_at':        scanned_at,
                }

                # ── Criterion 1: delta20 ─────────────────────────────
                if (D20_MIN_DTE <= dte <= D20_MAX_DTE
                        and D20_MIN_DELTA <= delta <= D20_MAX_DELTA
                        and mid >= D20_MIN_PREMIUM):
                    opps.append({**base, 'criteria': 'delta20'})

                # ── Criterion 2: otm20 ───────────────────────────────
                elif (OTM20_MIN_DTE <= dte <= OTM20_MAX_DTE
                        and otm_frac >= OTM20_MIN_OTM_PCT
                        and ann_roi >= OTM20_MIN_ANN_ROI):
                    opps.append({**base, 'criteria': 'otm20'})

                # ── Criterion 3: cheap ───────────────────────────────
                elif (price <= CHEAP_MAX_PRICE
                        and CHEAP_MIN_DTE <= dte <= CHEAP_MAX_DTE
                        and mid >= CHEAP_MIN_PREMIUM
                        and ann_roi >= CHEAP_MIN_ANN_ROI):
                    opps.append({**base, 'criteria': 'cheap'})

        # ── News check ───────────────────────────────────────────────
        if opps and max_dte_seen > 0:
            try:
                news_risk, news_flag = _check_news_risk(ticker, max_dte_seen)
                for opp in opps:
                    opp['news_risk'] = news_risk
                    opp['news_flag'] = news_flag
            except Exception:
                pass

        return opps
