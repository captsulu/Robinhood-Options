"""
Core monitoring engine.
Fetches Robinhood options positions, gets current prices,
evaluates assignment risk, and dispatches alerts.
"""

import logging
from datetime import datetime, date

import pytz

import alerts as alert_module
from config_manager import load_config
from database import log_price, log_alert, log_cash_snapshot, get_todays_snapshot_types
from robinhood_client import RobinhoodClient

logger = logging.getLogger(__name__)
ET = pytz.timezone('America/New_York')


# ── Market Hours ──────────────────────────────────────────────────────────────

def is_trading_window(config=None):
    """
    Return True if the current ET time falls within the configured window
    (default: 4:00 AM – 8:00 PM ET, Monday–Friday).
    """
    if config is None:
        config = load_config()

    now = datetime.now(ET)
    if now.weekday() >= 5:          # Saturday = 5, Sunday = 6
        return False

    mh = config.get('market_hours', {})
    start_str = mh.get('premarket_start', '04:00')
    end_str   = mh.get('aftermarket_end', '20:00')

    start = datetime.strptime(start_str, '%H:%M').time()
    end   = datetime.strptime(end_str,   '%H:%M').time()

    return start <= now.time() <= end


def needed_cash_snapshot() -> str | None:
    """
    Return 'open', 'close', or None depending on whether we should capture
    a cash snapshot right now.

    Windows (ET, weekdays only):
      open  → 9:30 – 10:14 AM  (first 45 min of regular session)
      close → 3:55 – 4:14 PM   (last 5 min of regular session + 14 min after bell)

    Each type is only taken once per calendar day; subsequent scans in the
    same window are no-ops.
    """
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return None

    h, m       = now.hour, now.minute
    taken      = get_todays_snapshot_types()
    is_open_w  = (h == 9  and m >= 30) or (h == 10 and m <= 14)
    is_close_w = (h == 15 and m >= 55) or (h == 16 and m <= 14)

    if is_open_w  and 'open'  not in taken:
        return 'open'
    if is_close_w and 'close' not in taken:
        return 'close'
    return None


def market_session_label():
    """Return a human-readable label for the current trading session."""
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return 'Weekend – Market Closed'
    t = now.time()

    def _t(s):
        return datetime.strptime(s, '%H:%M').time()

    if t < _t('04:00'):   return 'Overnight – Market Closed'
    if t < _t('09:30'):   return 'Pre-Market'
    if t < _t('16:00'):   return 'Regular Hours'
    if t < _t('20:00'):   return 'After-Hours'
    return 'Market Closed'


# ── Risk Math ─────────────────────────────────────────────────────────────────

def calculate_distance_pct(current_price: float, strike_price: float, option_type: str) -> float:
    """
    Return the percentage distance between the current price and the strike.

    Convention (positive = safe, negative = through strike / ITM):
      PUT  → positive when stock is ABOVE strike (you want it to stay above)
      CALL → positive when stock is BELOW strike  (you want it to stay below)
    """
    if option_type == 'put':
        return (current_price - strike_price) / strike_price * 100
    else:   # call
        return (strike_price - current_price) / strike_price * 100


def calculate_dte(expiration_date_str: str):
    """Days until expiration. Returns None if the date can't be parsed."""
    try:
        exp = datetime.strptime(expiration_date_str, '%Y-%m-%d').date()
        return (exp - date.today()).days
    except Exception:
        return None


def determine_status(distance_pct, dte, tolerance_pct, days_warning) -> str:
    """
    Classify the risk level for one position.

    Returns: 'safe' | 'warning' | 'critical'
    """
    if dte is None:
        return 'unknown'

    through_strike = distance_pct < 0                          # price past strike (ITM for short)
    in_zone        = through_strike or abs(distance_pct) <= tolerance_pct
    near_expiry    = dte <= days_warning

    # Critical only when expiry is close (≤ days_warning) — that's when rolling is urgent.
    # Being ITM or in the tolerance zone with time remaining = Warning (monitor, not panic).
    if (through_strike or in_zone) and near_expiry:
        return 'critical'       # ITM or in zone AND almost expired — roll now
    if through_strike or in_zone:
        return 'warning'        # ITM or close to strike but still has time
    return 'safe'


# ── Strategy Detection ────────────────────────────────────────────────────────

def detect_strategies(positions: list, owned_stock_symbols: set = None) -> list:
    """
    Examine all open options positions and label each with its strategy type.

    Strategy values:
      'covered_call'   – short call where Greg also holds ≥100 shares
      'call_spread'    – long call + short call, same symbol + expiration (vertical)
      'put_spread'     – long put  + short put,  same symbol + expiration (vertical)
      'cash_secured_put' – standalone short put
      'long_call'      – standalone long call
      'long_put'       – standalone long put
      'naked_call'     – short call with no stock (rare / flagged)
      'unknown'        – couldn't determine

    Each position also gets:
      spread_group  – shared ID string for both legs of a spread (None if not a spread)
      spread_leg    – 'long' | 'short' | None
    """
    from collections import defaultdict

    stock_syms = owned_stock_symbols or set()

    # Group by (symbol, option_type, expiration_date) to find spread pairs
    buckets: dict = defaultdict(list)
    for pos in positions:
        key = (pos['symbol'], pos['type'], pos['expiration_date'])
        buckets[key].append(pos)

    # Build annotation map: option_id → {strategy, spread_group, spread_leg}
    annotations: dict = {}

    for (sym, opt_type, exp), bucket in buckets.items():
        longs  = [p for p in bucket if p['position_type'] == 'long']
        shorts = [p for p in bucket if p['position_type'] == 'short']

        if longs and shorts:
            # Both legs present → it's a vertical spread
            spread_id = f"{sym}_{opt_type}_{exp}"
            for p in longs:
                annotations[p['id']] = {
                    'strategy':     f'{opt_type}_spread',   # 'call_spread' or 'put_spread'
                    'spread_group': spread_id,
                    'spread_leg':   'long',
                }
            for p in shorts:
                annotations[p['id']] = {
                    'strategy':     f'{opt_type}_spread',
                    'spread_group': spread_id,
                    'spread_leg':   'short',
                }
        else:
            # Single-sided position
            for p in bucket:
                if opt_type == 'call':
                    if p['position_type'] == 'short' and sym in stock_syms:
                        strategy = 'covered_call'
                    elif p['position_type'] == 'short':
                        strategy = 'naked_call'
                    else:
                        strategy = 'long_call'
                else:  # put
                    strategy = 'cash_secured_put' if p['position_type'] == 'short' else 'long_put'

                annotations[p['id']] = {
                    'strategy':     strategy,
                    'spread_group': None,
                    'spread_leg':   None,
                }

    # Merge annotations back into positions
    result = []
    for pos in positions:
        ann = annotations.get(pos['id'], {
            'strategy': 'unknown', 'spread_group': None, 'spread_leg': None
        })
        result.append({**pos, **ann})

    # Sort so spread legs sit adjacent; within a group sort long before short
    leg_order = {'short': 0, 'long': 1, None: 2}  # sell leg always on top
    result.sort(key=lambda p: (
        p['symbol'],
        p.get('spread_group') or '',
        leg_order.get(p.get('spread_leg'), 2),
        p['expiration_date'],
        p['strike_price'],
    ))

    return result


# ── Collateral Calculation ────────────────────────────────────────────────────

def calculate_collateral(positions: list) -> list:
    """
    Add a 'collateral' (float, cash locked) and 'collateral_type' (str) to
    every position.  Call AFTER detect_strategies so strategy / spread_leg
    annotations are already present.

    Rules (Robinhood cash/Instant account):
      cash_secured_put  → strike × 100 × qty
      put_spread short  → (short_strike - long_strike) × 100 × qty
      call_spread short → (long_strike  - short_strike) × 100 × qty
      covered_call      → 0  (stock-backed, not cash)
      any long leg      → 0  (premium already paid)
      naked_call        → 0  (margin/broker-specific; mark unknown)
    """
    from collections import defaultdict

    # Index positions by spread_group so we can compute spread widths
    spread_index: dict = defaultdict(list)
    for pos in positions:
        sg = pos.get('spread_group')
        if sg:
            spread_index[sg].append(pos)

    # Pre-compute spread widths
    spread_width: dict = {}   # spread_group → cash collateral per contract
    for sg, legs in spread_index.items():
        short = next((p for p in legs if p.get('spread_leg') == 'short'), None)
        long  = next((p for p in legs if p.get('spread_leg') == 'long'),  None)
        if short and long:
            width = abs(short['strike_price'] - long['strike_price'])
            spread_width[sg] = width

    # Annotate each position
    for pos in positions:
        sg       = pos.get('spread_group')
        strategy = pos.get('strategy', 'unknown')
        qty      = pos.get('quantity', 0)

        if strategy == 'cash_secured_put':
            pos['collateral']      = round(pos['strike_price'] * 100 * qty, 2)
            pos['collateral_type'] = 'cash_secured'

        elif strategy in ('put_spread', 'call_spread'):
            if pos.get('spread_leg') == 'short' and sg in spread_width:
                pos['collateral']      = round(spread_width[sg] * 100 * qty, 2)
                pos['collateral_type'] = 'spread_max_loss'
            else:
                pos['collateral']      = 0.0
                pos['collateral_type'] = 'protected_leg'

        elif strategy == 'covered_call':
            pos['collateral']      = 0.0
            pos['collateral_type'] = 'stock_secured'

        elif pos.get('position_type') == 'long':
            pos['collateral']      = 0.0
            pos['collateral_type'] = 'none'

        elif strategy == 'naked_call':
            pos['collateral']      = 0.0
            pos['collateral_type'] = 'margin'

        else:
            pos['collateral']      = 0.0
            pos['collateral_type'] = 'unknown'

    return positions


# ── Monitor Engine ────────────────────────────────────────────────────────────

class MonitorEngine:
    def __init__(self):
        self.client = RobinhoodClient()
        # Tracks which positions have already fired an alert this hour
        # key: "{option_id}_{YYYYMMDDH}"  value: status that was alerted
        self._alerted: dict = {}
        # Last known set of open option IDs — used to detect new/closed trades
        self._known_position_ids: set = set()

    def run_scan(self) -> dict:
        """
        Main entry point called by the scheduler and the API.
        Returns a dict consumed by the Flask /api/positions endpoint.
        """
        config      = load_config()
        tolerance   = config.get('tolerance_percent', 2.0)
        days_warn   = config.get('days_before_expiration_warning', 3)
        market_open = is_trading_window(config)
        session     = market_session_label()

        if not market_open:
            logger.info(f"Outside trading hours ({session}) – scan skipped")
            return {
                'positions':    [],
                'market_open':  False,
                'session':      session,
                'alert_count':  0,
                'message':      f'Outside trading hours – next window starts at 4:00 AM ET',
            }

        logger.info(f"Running scan ({session}) …")

        if not self.client.ensure_logged_in():
            return {
                'positions':   [],
                'market_open': market_open,
                'session':     session,
                'status':      'error',
                'message':     'Robinhood login failed – check credentials in .env',
            }

        positions = self.client.get_options_positions()

        if not positions:
            return {
                'positions':   [],
                'market_open': market_open,
                'session':     session,
                'alert_count': 0,
                'message':     'No open options positions found',
            }

        # ── Cash snapshot at open / close ────────────────────────────────────
        snap_type = needed_cash_snapshot()
        if snap_type:
            cash_info = self.client.get_account_cash_info()
            if cash_info:
                log_cash_snapshot(snap_type, **cash_info)
                logger.info(f"Cash snapshot ({snap_type}) saved – "
                            f"withdrawable ${cash_info['cash_available_for_withdrawal']:.2f}")
            _last_cash_info = cash_info
        else:
            _last_cash_info = None

        # Detect strategy type for each position (spread / covered call / CSP …)
        owned_stocks = self.client.get_owned_stock_symbols()
        positions    = detect_strategies(positions, owned_stock_symbols=owned_stocks)
        positions    = calculate_collateral(positions)

        # Fetch prices in one batch call
        symbols     = list({p['symbol'] for p in positions})
        price_map   = self.client.get_prices_batch(symbols)

        enriched    = []
        alert_count = 0

        for pos in positions:
            symbol   = pos['symbol']
            strike   = pos['strike_price']
            exp_date = pos['expiration_date']
            opt_type = pos['type']          # 'call' or 'put'
            pos_type = pos['position_type'] # 'long' or 'short'

            current_price = price_map.get(symbol)
            if current_price is None:
                logger.warning(f"No price for {symbol} – skipping")
                continue

            # Log every price point to DB
            log_price(symbol, current_price)

            dist_pct = calculate_distance_pct(current_price, strike, opt_type)
            dte      = calculate_dte(exp_date)

            # ── Assignment risk logic ─────────────────────────────────────────
            # Long legs of spreads are PROTECTION, not risk.
            # Only the SHORT leg (the one we sold) can be assigned against us.
            # Example: QQQ put spread → sell $650 put, buy $640 put.
            #   We only care if QQQ falls near $650 (the short leg).
            #   The $640 long leg is our hedge — it should never generate a warning.
            if pos.get('spread_leg') == 'long':
                status = 'safe'
            else:
                status = determine_status(dist_pct, dte, tolerance, days_warn)

            # Fire alert only for short legs (or standalone positions) at risk.
            # Throttled to once per hour per position+status combination.
            hour_key = f"{pos['id']}_{datetime.now(ET).strftime('%Y%m%d%H')}"
            if status in ('warning', 'critical') and self._alerted.get(hour_key) != status:
                self._alerted[hour_key] = status
                alert_count += 1

                msg = (
                    f"{'CRITICAL' if status == 'critical' else 'WARNING'}: "
                    f"{symbol} {opt_type.upper()} ${strike:.2f} exp {exp_date} | "
                    f"Price: ${current_price:.2f} | "
                    f"Distance: {abs(dist_pct):.1f}% | "
                    f"DTE: {dte}"
                )

                log_alert(symbol, pos['id'], status, msg, strike,
                          current_price, dist_pct, exp_date, dte)

                enriched_pos_for_alert = {
                    **pos,
                    'current_price': current_price,
                    'distance_pct':  round(dist_pct, 2),
                    'dte':           dte,
                    'status':        status,
                }
                alert_module.send_alert(status, symbol, msg, enriched_pos_for_alert)

            enriched.append({
                **pos,
                'current_price': round(current_price, 4),
                'distance_pct':  round(dist_pct, 2),
                'dte':           dte,
                'status':        status,
            })

        # ── Detect new/closed trades → take cash snapshot ────────────────────
        current_ids = {p['id'] for p in enriched}
        if current_ids != self._known_position_ids and self._known_position_ids:
            opened = current_ids - self._known_position_ids
            closed = self._known_position_ids - current_ids
            change_desc = []
            if opened:
                change_desc.append(f"new position(s): {', '.join(opened)}")
            if closed:
                change_desc.append(f"closed position(s): {', '.join(closed)}")
            logger.info(f"Position change detected – {'; '.join(change_desc)}")

            trade_cash = _last_cash_info or self.client.get_account_cash_info()
            if trade_cash:
                log_cash_snapshot('trade', **trade_cash)
                logger.info(f"Trade cash snapshot saved – "
                            f"withdrawable ${trade_cash['cash_available_for_withdrawal']:.2f}")

        self._known_position_ids = current_ids

        total_collateral = round(sum(p.get('collateral', 0) for p in enriched), 2)
        logger.info(
            f"Scan complete – {len(enriched)} positions, {alert_count} new alerts, "
            f"${total_collateral:.2f} total collateral locked"
        )

        return {
            'positions':        enriched,
            'market_open':      market_open,
            'session':          session,
            'alert_count':      alert_count,
            'total_collateral': total_collateral,
        }
