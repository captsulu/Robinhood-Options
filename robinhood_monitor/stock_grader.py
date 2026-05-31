"""
Benjamin Graham / Warren Buffett stock grading.

Graham Number (intrinsic value):
    √(22.5 × EPS_TTM × BookValuePerShare)

Scoring (0 – 5 points):
  1.0  P/E ≤ 15          (Graham's max fair P/E)
  0.5  P/E 15 – 25       (acceptable)
  1.0  P/B ≤ 1.5         (Graham's max P/B)
  0.5  P/B 1.5 – 3.0
  1.5  Margin of Safety ≥ 30 %
  1.0  Margin of Safety 15 – 29 %
  0.5  Margin of Safety 0 – 14 %
  1.0  Positive TTM Free Cash Flow
  0.5  P/E × P/B < 22.5  (Graham combined test)
  ─────────────────────────
  5.0  maximum

Grade:  A ≥ 4.0 | B ≥ 3.0 | C ≥ 2.0 | D ≥ 1.0 | F < 1.0

Results are cached in-process for CACHE_TTL_HOURS to avoid hammering Yahoo.
"""

import logging
import time
from datetime import datetime

logger = logging.getLogger(__name__)

# ── In-process cache ──────────────────────────────────────────────────────────
CACHE_TTL_HOURS = 4
_cache: dict = {}   # symbol → {data: dict, ts: float}


def _cached(symbol: str):
    entry = _cache.get(symbol.upper())
    if entry and (time.time() - entry['ts']) < CACHE_TTL_HOURS * 3600:
        return entry['data']
    return None


def _store(symbol: str, data: dict):
    _cache[symbol.upper()] = {'data': data, 'ts': time.time()}


# ── Core grader ───────────────────────────────────────────────────────────────

def grade_stock(symbol: str) -> dict:
    """
    Fetch fundamentals from Yahoo Finance and return a Graham grade dict.
    Returns a dict with 'error' key if the fetch fails.
    """
    sym = symbol.upper()

    cached = _cached(sym)
    if cached:
        logger.debug(f"Graham grade cache hit: {sym}")
        return cached

    try:
        import yfinance as yf
    except ImportError:
        return {'symbol': sym, 'error': 'yfinance not installed'}

    try:
        ticker = yf.Ticker(sym)
        info   = ticker.info or {}

        # Check if options are listed on this symbol (lightweight call)
        try:
            has_options = bool(ticker.options)
        except Exception:
            has_options = False

        # ── Pull raw fields ───────────────────────────────────────────────────
        def _f(key, default=None):
            v = info.get(key)
            try:
                return float(v) if v is not None else default
            except (TypeError, ValueError):
                return default

        price        = _f('currentPrice') or _f('regularMarketPrice') or _f('previousClose')
        eps_ttm      = _f('trailingEps')
        bvps         = _f('bookValue')          # book value per share
        fcf          = _f('freeCashflow')        # total TTM free cash flow ($)
        shares       = _f('sharesOutstanding')
        pe           = _f('trailingPE')
        pb           = _f('priceToBook')
        high_52w     = _f('fiftyTwoWeekHigh')
        low_52w      = _f('fiftyTwoWeekLow')
        name         = info.get('shortName') or info.get('longName') or sym
        sector       = info.get('sector', '')
        industry     = info.get('industry', '')

        if not price:
            result = {'symbol': sym, 'error': 'No price data available'}
            _store(sym, result)
            return result

        # ── Graham Number ─────────────────────────────────────────────────────
        graham_number = None
        if eps_ttm and eps_ttm > 0 and bvps and bvps > 0:
            graham_number = (22.5 * eps_ttm * bvps) ** 0.5

        # ── Margin of safety ─────────────────────────────────────────────────
        margin_of_safety = None
        if graham_number and price and price > 0:
            margin_of_safety = (graham_number - price) / graham_number * 100

        # ── FCF per share ─────────────────────────────────────────────────────
        fcf_per_share = None
        if fcf is not None and shares and shares > 0:
            fcf_per_share = fcf / shares

        # ── Scoring ───────────────────────────────────────────────────────────
        score = 0.0

        # 1. P/E ratio
        if pe and 0 < pe <= 15:
            score += 1.0
        elif pe and 15 < pe <= 25:
            score += 0.5

        # 2. P/B ratio
        if pb and 0 < pb <= 1.5:
            score += 1.0
        elif pb and 1.5 < pb <= 3.0:
            score += 0.5

        # 3. Margin of Safety
        if margin_of_safety is not None:
            if margin_of_safety >= 30:
                score += 1.5
            elif margin_of_safety >= 15:
                score += 1.0
            elif margin_of_safety >= 0:
                score += 0.5

        # 4. Positive FCF
        if fcf is not None and fcf > 0:
            score += 1.0

        # 5. Graham combined test  P/E × P/B < 22.5
        if pe and pb and pe > 0 and pb > 0 and pe * pb < 22.5:
            score += 0.5

        score = round(min(score, 5.0), 1)

        # ── Letter grade ──────────────────────────────────────────────────────
        if score >= 4.0:
            grade = 'A'
        elif score >= 3.0:
            grade = 'B'
        elif score >= 2.0:
            grade = 'C'
        elif score >= 1.0:
            grade = 'D'
        else:
            grade = 'F'

        # ── % of 52-week high ─────────────────────────────────────────────────
        pct_of_ath = None
        if high_52w and high_52w > 0 and price:
            pct_of_ath = round(price / high_52w * 100, 1)

        result = {
            'symbol':           sym,
            'name':             name,
            'sector':           sector,
            'industry':         industry,
            'current_price':    round(price, 2)           if price          else None,
            'intrinsic_value':  round(graham_number, 2)   if graham_number  else None,
            'fair_value':       round(graham_number, 2)   if graham_number  else None,
            'ath_52w':          round(high_52w, 2)        if high_52w       else None,
            'low_52w':          round(low_52w, 2)         if low_52w        else None,
            'pct_of_ath':       pct_of_ath,
            'margin_of_safety': round(margin_of_safety, 1) if margin_of_safety is not None else None,
            'eps_ttm':          round(eps_ttm, 4)         if eps_ttm        else None,
            'bvps':             round(bvps, 2)            if bvps           else None,
            'pe_ratio':         round(pe, 2)              if pe             else None,
            'pb_ratio':         round(pb, 2)              if pb             else None,
            'ttm_fcf':          int(fcf)                  if fcf            else None,
            'fcf_per_share':    round(fcf_per_share, 2)   if fcf_per_share  else None,
            'score':            score,
            'grade':            grade,
            'has_options':       has_options,
            'cached_at':        datetime.now().strftime('%Y-%m-%d %H:%M'),
        }

        logger.info(
            f"Graham grade {sym}: price=${price:.2f}  intrinsic="
            f"{'$'+str(round(graham_number,2)) if graham_number else 'N/A'}  "
            f"MoS={str(round(margin_of_safety,1))+'%' if margin_of_safety is not None else 'N/A'}  "
            f"score={score}  grade={grade}"
        )
        _store(sym, result)
        return result

    except Exception as e:
        logger.error(f"Graham grade error for {sym}: {e}")
        result = {'symbol': sym, 'error': str(e)}
        return result


def bust_cache(symbol: str = None):
    """Clear the grade cache for one symbol (or all if None)."""
    if symbol:
        _cache.pop(symbol.upper(), None)
    else:
        _cache.clear()
