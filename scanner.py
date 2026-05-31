"""
================================================================================
  BARCHART AUTO-SCANNER  |  Cash-Secured Put Opportunity Finder
================================================================================

This module automatically finds the best put-selling opportunity within a
given cash budget. It works in two stages:

  STAGE 1 — FIND CANDIDATES
    Tries Barchart.com's internal screener for high-IV stocks.
    Falls back to yfinance + a curated watchlist if Barchart is unavailable.

  STAGE 2 — SCORE AND RECOMMEND
    Pulls live option chains for each candidate.
    Filters for puts within your cash budget ($500 max by default).
    Scores each opportunity and returns a ranked recommendation.

SCORING CRITERIA (higher = better):
  • Annualized Premium Yield  — how much you earn relative to the cash tied up
  • IV Rank / Implied Volatility — high IV = fatter premiums
  • OTM Buffer                — how far the stock needs to fall before you're
                                 assigned (safety cushion)
  • Liquidity                 — bid/ask spread + open interest

$500 BUDGET NOTE:
  A cash-secured put requires: Strike × 100 shares in reserved cash.
  With $500, the max strike is $5.00.
  This script targets stocks priced $3–$12 where meaningful $3–$5 puts exist.

Author: Built for Greg | Paper Trading Use Only
================================================================================
"""

import time
import json
import requests
import yfinance as yf
from datetime import datetime, timedelta

# ── CONFIGURATION ─────────────────────────────────────────────────────────────

MAX_BUDGET           = 500      # Maximum cash to reserve for one put contract
MAX_STRIKE           = MAX_BUDGET / 100   # = $5.00 (strike × 100 shares ≤ budget)
MIN_PREMIUM_DOLLARS  = 0.10     # Minimum premium per share ($10 per contract)
MIN_OPEN_INTEREST    = 50       # Minimum open interest — avoids illiquid options
MAX_BID_ASK_SPREAD   = 0.50     # Max allowed spread — keeps fill prices fair
MIN_DTE              = 7        # Minimum days to expiration
MAX_DTE              = 21       # Maximum days to expiration
MIN_OTM_BUFFER_PCT   = 5        # Put must be at least 5% below current stock price

# ── WATCHLIST ─────────────────────────────────────────────────────────────────
# These are stocks in the $3–$15 range that commonly have liquid put options
# near the $5 strike. Selected for volatility, options volume, and relevance.
#
# WHY THESE?
#   - They're optionable (meet exchange listing requirements)
#   - They have enough volume to get decent fills
#   - Their price range makes $3–$5 puts realistic (not pointlessly far OTM)

FALLBACK_WATCHLIST = [
    "MARA",   # Marathon Digital — crypto miner, high volatility
    "RIOT",   # Riot Platforms  — crypto miner, high volatility
    "SOFI",   # SoFi Technologies — fintech, active options market
    "GRAB",   # Grab Holdings   — SE Asian tech/delivery, volatile
    "TLRY",   # Tilray Brands   — cannabis, frequently near $5
    "HOOD",   # Robinhood Markets — fintech brokerage
    "VALE",   # Vale S.A.        — Brazilian miner, trades ~$8–$12
    "NOK",    # Nokia            — telecom, low price, options available
    "ERIC",   # Ericsson         — telecom, similar to NOK
    "SNDL",   # Sundial Growers  — cannabis, very low price
    "CLOV",   # Clover Health    — healthtech, volatile
    "WULF",   # TeraWulf         — crypto miner, sub-$5 range
    "CIFR",   # Cipher Mining    — crypto miner, sub-$5 range
    "HIMS",   # Hims & Hers      — telehealth, options active
    "OPEN",   # Opendoor Tech   — proptech, volatile
]

# ── BARCHART INTERNAL API ──────────────────────────────────────────────────────
# Barchart's website uses internal REST endpoints to load screener data.
# These work with standard browser-like headers. No API key required.
# If Barchart changes their site, the yfinance fallback kicks in automatically.

BARCHART_SCREENER_URL = (
    "https://www.barchart.com/proxies/core-api/v1/quotes/get"
    "?lists=options.mostActive.us"
    "&fields=symbol,lastPrice,priceChange,percentChange,highPrice,lowPrice,"
    "volume,impliedVolatility,historicalVolatility,optionVolume,putVolume,"
    "callVolume,putCallVolumeRatio&orderBy=optionVolume&orderDir=desc"
    "&startsWith=&page=1&limit=50&raw=1"
)

BARCHART_HIGH_IV_URL = (
    "https://www.barchart.com/proxies/core-api/v1/quotes/get"
    "?lists=options.highImpliedVolatility.stocks"
    "&fields=symbol,lastPrice,impliedVolatility,historicalVolatility,"
    "ivRank,ivPercentile,optionVolume&orderBy=impliedVolatility"
    "&orderDir=desc&page=1&limit=50&raw=1"
)

BARCHART_HEADERS = {
    "User-Agent"      : "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept"          : "application/json",
    "Accept-Language" : "en-US,en;q=0.9",
    "Referer"         : "https://www.barchart.com/options/most-active/stocks",
}


# ══════════════════════════════════════════════════════════════════════════════
#  STAGE 1 — CANDIDATE DISCOVERY
# ══════════════════════════════════════════════════════════════════════════════

def fetch_barchart_candidates():
    """
    Tries to pull high-IV or most-active options candidates from Barchart.com.

    Returns a list of stock symbols (strings), e.g. ["MARA", "RIOT", "SOFI"]
    Returns an empty list if Barchart is unreachable — the caller falls back
    to FALLBACK_WATCHLIST in that case.
    """
    symbols = []

    for url, label in [(BARCHART_HIGH_IV_URL,  "High-IV screener"),
                       (BARCHART_SCREENER_URL, "Most-active screener")]:
        try:
            resp = requests.get(url, headers=BARCHART_HEADERS, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                rows = data.get("data", [])
                for row in rows:
                    sym   = row.get("raw", {}).get("symbol", "")
                    price = row.get("raw", {}).get("lastPrice", 0)
                    # Only include stocks priced low enough to have strikes ≤ $5
                    if sym and isinstance(price, (int, float)) and price <= 15:
                        if sym not in symbols:
                            symbols.append(sym)
                print(f"  ✅ Barchart {label}: found {len(symbols)} candidates so far.")
            else:
                print(f"  ⚠️  Barchart {label} returned status {resp.status_code}.")
        except Exception as e:
            print(f"  ⚠️  Barchart {label} failed: {e}")

    return symbols


def get_candidate_list():
    """
    Main entry point for Stage 1.
    Tries Barchart first. If it returns fewer than 5 symbols, supplements
    with the built-in FALLBACK_WATCHLIST.

    Returns a deduplicated list of ticker symbols to scan.
    """
    print("\n  🔍 Finding candidates...")
    barchart_symbols = fetch_barchart_candidates()

    if len(barchart_symbols) >= 5:
        print(f"  📊 Using {len(barchart_symbols)} Barchart candidates.")
        return barchart_symbols

    # Barchart didn't return enough — supplement with watchlist
    combined = list(barchart_symbols)  # start with whatever Barchart gave us
    for sym in FALLBACK_WATCHLIST:
        if sym not in combined:
            combined.append(sym)

    source = "Barchart + built-in watchlist" if barchart_symbols else "built-in watchlist"
    print(f"  📋 Using {source} ({len(combined)} symbols).")
    return combined


# ══════════════════════════════════════════════════════════════════════════════
#  STAGE 2 — LIVE QUOTES
# ══════════════════════════════════════════════════════════════════════════════

def get_live_quote(symbol):
    """
    Fetches the current price and timestamp for a stock using Yahoo Finance.

    Returns a dict:
      {
        "symbol"    : "MARA",
        "price"     : 7.42,
        "timestamp" : "2024-03-15 10:32:05 EDT",
        "valid"     : True
      }

    Returns {"valid": False} if the stock can't be found or has no price.
    """
    try:
        ticker  = yf.Ticker(symbol)
        info    = ticker.fast_info          # Faster than full .info dict

        price   = info.last_price
        if not price or price <= 0:
            return {"valid": False, "symbol": symbol}

        # Get a human-readable timestamp
        ts_raw  = getattr(info, "last_volume_time", None)
        if ts_raw:
            # yfinance gives UTC timestamps — convert to readable string
            timestamp = datetime.utcfromtimestamp(ts_raw).strftime("%Y-%m-%d %H:%M UTC")
        else:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M local")

        return {
            "symbol"    : symbol,
            "price"     : round(float(price), 2),
            "timestamp" : timestamp,
            "valid"     : True,
        }

    except Exception:
        return {"valid": False, "symbol": symbol}


def print_quote(quote):
    """Prints a formatted single-line quote: MARA  $7.42  [2024-03-15 10:32 UTC]"""
    if quote["valid"]:
        print(f"  {quote['symbol']:<8}  ${quote['price']:<8.2f}  [{quote['timestamp']}]")
    else:
        print(f"  {quote['symbol']:<8}  (no quote available)")


# ══════════════════════════════════════════════════════════════════════════════
#  STAGE 3 — OPTIONS SCANNING
# ══════════════════════════════════════════════════════════════════════════════

def get_expiration_dates_in_range(ticker_obj):
    """
    Returns a list of expiration date strings (from yfinance) that fall
    within our MIN_DTE to MAX_DTE window.
    """
    today      = datetime.today().date()
    min_date   = today + timedelta(days=MIN_DTE)
    max_date   = today + timedelta(days=MAX_DTE)

    valid_dates = []
    try:
        for exp_str in ticker_obj.options:
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
            if min_date <= exp_date <= max_date:
                valid_dates.append(exp_str)
    except Exception:
        pass

    return valid_dates


def scan_puts_for_symbol(symbol, current_price):
    """
    Scans the options chain for a given symbol and finds puts that:
      1. Expire within our DTE window (7–21 days)
      2. Have a strike price ≤ MAX_STRIKE ($5.00)
      3. Are out of the money (strike < current price)
      4. Have enough premium and liquidity

    Returns a list of opportunity dicts, one per qualifying put.
    Each dict contains everything needed for scoring and display.
    """
    opportunities = []

    try:
        ticker      = yf.Ticker(symbol)
        exp_dates   = get_expiration_dates_in_range(ticker)

        if not exp_dates:
            return []

        for exp_str in exp_dates:
            try:
                chain = ticker.option_chain(exp_str)
                puts  = chain.puts

                if puts is None or puts.empty:
                    continue

                exp_date    = datetime.strptime(exp_str, "%Y-%m-%d").date()
                dte         = (exp_date - datetime.today().date()).days

                for _, row in puts.iterrows():
                    strike  = float(row.get("strike", 0))
                    bid     = float(row.get("bid", 0))
                    ask     = float(row.get("ask", 0))
                    volume  = int(row.get("volume", 0) or 0)
                    oi      = int(row.get("openInterest", 0) or 0)
                    iv      = float(row.get("impliedVolatility", 0) or 0)
                    mid     = round((bid + ask) / 2, 2)

                    # ── FILTER CHECKS ──────────────────────────────────────

                    # 1. Within budget
                    if strike > MAX_STRIKE:
                        continue

                    # 2. Must be out of the money
                    if strike >= current_price:
                        continue

                    # 3. Enough premium to be worth selling
                    if mid < MIN_PREMIUM_DOLLARS:
                        continue

                    # 4. Enough liquidity
                    if oi < MIN_OPEN_INTEREST:
                        continue

                    # 5. Bid-ask spread not too wide (hard to fill midpoint)
                    if (ask - bid) > MAX_BID_ASK_SPREAD:
                        continue

                    # 6. Enough OTM buffer (safety cushion)
                    otm_buffer_pct = ((current_price - strike) / current_price) * 100
                    if otm_buffer_pct < MIN_OTM_BUFFER_PCT:
                        continue

                    # ── COMPUTE SCORES ─────────────────────────────────────

                    cash_required       = strike * 100
                    premium_per_contract = mid * 100

                    # Annualized yield: what % return on cash if we do this
                    # every similar period all year
                    annualized_yield = (mid / strike) * (365 / dte) * 100

                    opportunities.append({
                        "symbol"             : symbol,
                        "current_price"      : current_price,
                        "strike"             : strike,
                        "expiration"         : exp_str,
                        "dte"                : dte,
                        "bid"                : bid,
                        "ask"                : ask,
                        "mid"                : mid,
                        "iv"                 : round(iv * 100, 1),   # as percentage
                        "volume"             : volume,
                        "open_interest"      : oi,
                        "cash_required"      : round(cash_required, 2),
                        "premium_per_contract": round(premium_per_contract, 2),
                        "otm_buffer_pct"     : round(otm_buffer_pct, 1),
                        "annualized_yield"   : round(annualized_yield, 1),
                    })

            except Exception:
                continue

    except Exception:
        pass

    return opportunities


# ══════════════════════════════════════════════════════════════════════════════
#  STAGE 4 — SCORING AND RECOMMENDATION
# ══════════════════════════════════════════════════════════════════════════════

def score_opportunity(opp):
    """
    Assigns a composite score to a put-selling opportunity.

    Higher score = better opportunity overall.

    Scoring breakdown (all normalized 0–100, then weighted):
      40%  Annualized Yield   — primary income metric
      25%  IV (Volatility)    — higher IV = better premium environment
      20%  OTM Buffer         — safety: how far stock needs to fall to hurt us
      15%  Liquidity          — open interest + tight spread
    """
    # ── Yield score (0–100) ──────────────────────────────────────────────────
    # Cap at 500% annualized (anything higher is likely garbage data)
    yield_score   = min(opp["annualized_yield"] / 500 * 100, 100)

    # ── IV score (0–100) ────────────────────────────────────────────────────
    # 100% IV = full score; below 20% = near zero
    iv_score      = min(opp["iv"] / 100 * 100, 100)

    # ── OTM buffer score (0–100) ─────────────────────────────────────────────
    # 30% or more OTM = full score; 5% OTM = low score
    buffer_score  = min((opp["otm_buffer_pct"] - MIN_OTM_BUFFER_PCT) / 25 * 100, 100)
    buffer_score  = max(buffer_score, 0)

    # ── Liquidity score (0–100) ───────────────────────────────────────────────
    # OI of 500+ = good; spread < 0.05 = good
    oi_score      = min(opp["open_interest"] / 500 * 100, 100)
    spread        = opp["ask"] - opp["bid"]
    spread_score  = max(100 - (spread / MAX_BID_ASK_SPREAD * 100), 0)
    liq_score     = (oi_score + spread_score) / 2

    # ── Composite (weighted) ──────────────────────────────────────────────────
    composite = (
        yield_score  * 0.40 +
        iv_score     * 0.25 +
        buffer_score * 0.20 +
        liq_score    * 0.15
    )

    return round(composite, 1)


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN ENTRY POINT — AUTO_RECOMMEND
# ══════════════════════════════════════════════════════════════════════════════

def auto_recommend(budget=500):
    """
    Full pipeline: discover → quote → scan → score → recommend.

    Prints progress as it runs, then returns a ranked list of the top
    opportunities found, each with a composite score and all trade details.

    budget: Maximum cash to reserve for one put contract (default $500)
    """
    global MAX_STRIKE, MAX_BUDGET
    MAX_BUDGET = budget
    MAX_STRIKE = budget / 100

    print("\n" + "="*65)
    print(f"  AUTO-SCAN  |  Budget: ${budget:.0f}  |  Max Strike: ${MAX_STRIKE:.2f}")
    print("="*65)

    # ── STAGE 1: Get candidate symbols ────────────────────────────────────────
    candidates = get_candidate_list()

    # ── STAGE 2 + 3: Quote and scan each candidate ────────────────────────────
    print(f"\n  📡 Fetching live quotes and scanning options chains...")
    print(f"  {'SYMBOL':<8}  {'PRICE':<10}  {'TIMESTAMP'}")
    print("  " + "-"*55)

    all_opportunities = []

    for symbol in candidates:
        # Get live quote
        quote = get_live_quote(symbol)

        if not quote["valid"]:
            continue

        # Print the live quote line
        print_quote(quote)

        # Only scan if stock is priced high enough to have meaningful OTM puts
        # (Stock must be above our max strike to have any OTM puts at that strike)
        if quote["price"] <= MAX_STRIKE:
            # Stock is AT or BELOW the strike — any put would be ITM or ATM
            # These are higher-risk. Still scan, but note it.
            pass

        # Scan options chain
        opps = scan_puts_for_symbol(symbol, quote["price"])
        all_opportunities.extend(opps)

        # Small delay to be polite to Yahoo Finance's servers
        time.sleep(0.3)

    # ── STAGE 4: Score and rank ───────────────────────────────────────────────
    if not all_opportunities:
        print("\n  ❌ No qualifying opportunities found within the $500 budget.")
        print("     Possible reasons:")
        print("     • Markets are closed (options prices go stale after hours)")
        print("     • No stocks in the watchlist have $5-or-under puts with enough premium")
        print("     • Try running again during market hours (9:30am–4pm ET)")
        return []

    for opp in all_opportunities:
        opp["score"] = score_opportunity(opp)

    # Sort best first
    ranked = sorted(all_opportunities, key=lambda x: x["score"], reverse=True)

    # ── PRINT RECOMMENDATIONS ─────────────────────────────────────────────────
    print(f"\n\n  🏆 TOP RECOMMENDATIONS  (out of {len(ranked)} qualifying puts found)")
    print("  " + "="*65)

    top_3 = ranked[:3]
    for i, opp in enumerate(top_3, 1):
        medal = ["🥇", "🥈", "🥉"][i - 1]
        print(f"\n  {medal}  RANK #{i} — {opp['symbol']}  |  Score: {opp['score']}/100")
        print(f"     Current Price : ${opp['current_price']:.2f}")
        print(f"     Strike        : ${opp['strike']:.2f}  ({opp['otm_buffer_pct']:.1f}% below current price)")
        print(f"     Expiration    : {opp['expiration']}  ({opp['dte']} days away)")
        print(f"     Premium (mid) : ${opp['mid']:.2f}/share  →  ${opp['premium_per_contract']:.2f} per contract")
        print(f"     Cash Required : ${opp['cash_required']:.2f}  (within your ${budget:.0f} budget ✅)")
        print(f"     Implied Vol.  : {opp['iv']:.1f}%")
        print(f"     Open Interest : {opp['open_interest']:,}")
        print(f"     Annual. Yield : {opp['annualized_yield']:.1f}%  (if you repeated this trade all year)")
        print(f"     Bid / Ask     : ${opp['bid']:.2f} / ${opp['ask']:.2f}")

    print("\n  " + "-"*65)

    # ── TOP PICK EXPLANATION ──────────────────────────────────────────────────
    if top_3:
        best = top_3[0]
        print(f"\n  💡 RECOMMENDATION: Sell the {best['symbol']} ${best['strike']:.2f} Put")
        print(f"     expiring {best['expiration']} for approximately ${best['mid']:.2f}/share.")
        print(f"\n     What this means:")
        print(f"     • You collect ${best['premium_per_contract']:.2f} in premium immediately.")
        print(f"     • You reserve ${best['cash_required']:.2f} in cash as collateral.")
        print(f"     • If {best['symbol']} stays above ${best['strike']:.2f} at expiration,")
        print(f"       you keep the ${best['premium_per_contract']:.2f} and the trade is done.")
        print(f"     • If {best['symbol']} drops below ${best['strike']:.2f}, you buy")
        print(f"       100 shares at ${best['strike']:.2f} each (${best['cash_required']:.2f} total).")
        print(f"     • The stock would need to fall {best['otm_buffer_pct']:.1f}% from here to assign you.")
        print()

    return ranked
