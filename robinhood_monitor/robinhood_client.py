"""
Robinhood API client using the unofficial robin_stocks library.
Credentials are loaded from the .env file (ROBINHOOD_USERNAME / ROBINHOOD_PASSWORD).
"""

import os
import logging
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))
logger = logging.getLogger(__name__)


class RobinhoodClient:
    def __init__(self):
        self._logged_in = False
        # Auth state exposed to the dashboard
        self.auth_status  = 'disconnected'  # disconnected | connecting | needs_mfa | ok | error
        self.auth_message = 'Not yet connected'
        self._username    = None
        self._password    = None

    # ── Auth ─────────────────────────────────────────────────────────────────

    def ensure_logged_in(self):
        if self._logged_in:
            return True
        # Do not auto-retry when in error or needs_mfa state —
        # wait for the user to act via the dashboard overlay.
        if self.auth_status in ('error', 'needs_mfa'):
            return False
        return self.login()

    def login(self, mfa_code=None):
        """
        Attempt Robinhood login.
        If MFA is required and no mfa_code is supplied, sets auth_status='needs_mfa'
        and returns False so the dashboard can prompt the user.
        """
        import robin_stocks.robinhood as rh
        self._patch_robin_stocks(rh)

        username = self._username or os.getenv('ROBINHOOD_USERNAME')
        password = self._password or os.getenv('ROBINHOOD_PASSWORD')

        if not username or not password:
            self.auth_status  = 'error'
            self.auth_message = 'ROBINHOOD_USERNAME or ROBINHOOD_PASSWORD not set in .env'
            logger.error(self.auth_message)
            return False

        # Cache credentials so submit_mfa() can use them without re-reading env
        self._username = username
        self._password = password

        self.auth_status  = 'connecting'
        self.auth_message = 'Connecting to Robinhood...'

        # Always clear stale pickle before attempting login to avoid
        # the robin_stocks 'token_type' key error on expired sessions.
        self._clear_pickle()

        try:
            rh.login(username, password,
                     mfa_code=mfa_code,
                     store_session=False)

            # rh.login() sometimes prints warnings but returns normally.
            # If no exception was raised, treat the session as established.
            # The session error detector in API calls will catch any broken state.
            self._logged_in   = True
            self.auth_status  = 'ok'
            self.auth_message = 'Connected'
            logger.info("Logged in to Robinhood successfully")
            self._notify_desktop("Robinhood Connected", "Successfully logged in.")
            return True

        except Exception as e:
            err = str(e).lower()
            self._logged_in = False

            # Detect MFA / 2FA requirement
            mfa_keywords = ['mfa', 'two factor', '2fa', 'verification code',
                            'multi-factor', 'one-time', 'sms code', 'challenge']
            if any(kw in err for kw in mfa_keywords) or (
                    'enter' in err and 'code' in err):
                self.auth_status  = 'needs_mfa'
                self.auth_message = 'MFA required — enter the code sent to your phone/email.'
                logger.warning("Robinhood login requires MFA code")
                self._notify_desktop(
                    "Robinhood — Action Required",
                    "Open the dashboard and enter your MFA code to connect."
                )
            else:
                self.auth_status  = 'error'
                self.auth_message = f'Login failed: {e}'
                logger.error(f"Robinhood login failed: {e}")
                self._notify_desktop(
                    "Robinhood Login Failed",
                    f"Check credentials in .env — {e}"
                )
            return False

    def submit_mfa(self, code):
        """Submit the MFA code received by the user and complete login."""
        logger.info("Submitting MFA code to Robinhood")
        return self.login(mfa_code=code.strip())

    def retry_login(self):
        """Force a fresh login attempt — clears stale session file first."""
        self._logged_in   = False
        self.auth_status  = 'connecting'
        self.auth_message = 'Retrying...'
        self._clear_pickle()
        return self.login()

    def get_auth_state(self):
        return {
            'status':  self.auth_status,
            'message': self.auth_message,
            'logged_in': self._logged_in,
        }

    def _patch_robin_stocks(self, rh):
        """
        Monkey-patch robin_stocks to inject a default token_type='Bearer' when
        Robinhood omits it from the OAuth response. The patch must be applied in
        the authentication module's namespace (not just helper) because
        authentication.py binds request_post at import time via
        'from helper import request_post'.
        """
        try:
            import robin_stocks.robinhood.helper         as rh_helper
            import robin_stocks.robinhood.authentication as rh_auth

            if getattr(rh_auth, '_patched_by_monitor', False):
                return  # already patched this session

            # Choose the original function from whichever module has it
            _orig = getattr(rh_auth, 'request_post',
                            getattr(rh_helper, 'request_post', None))
            if _orig is None:
                logger.warning("Could not find request_post to patch")
                return

            def _safe_post(url, payload=None, **kwargs):
                result = _orig(url, payload, **kwargs)
                if isinstance(result, dict):
                    if 'access_token' in result and 'token_type' not in result:
                        result['token_type'] = 'Bearer'
                        logger.info("Injected token_type=Bearer into auth response")
                return result

            # Patch in both modules so whichever binding is active gets fixed
            if hasattr(rh_auth,   'request_post'): rh_auth.request_post   = _safe_post
            if hasattr(rh_helper, 'request_post'): rh_helper.request_post = _safe_post

            rh_auth._patched_by_monitor = True
            logger.info("robin_stocks auth patch applied (authentication + helper)")
        except Exception as patch_err:
            logger.warning(f"Could not patch robin_stocks: {patch_err}")

    def _clear_pickle(self):
        """Delete ALL stale robin_stocks session pickle files."""
        import glob
        patterns = [
            os.path.join(os.path.expanduser('~'), '.tokens', '*.pickle'),
            os.path.join(os.path.expanduser('~'), '.tokens', '*'),      # no extension
            os.path.join(os.path.dirname(os.path.abspath(__file__)), '*.pickle'),
        ]
        for pattern in patterns:
            for f in glob.glob(pattern):
                try:
                    os.remove(f)
                    logger.info(f"Removed stale session file: {f}")
                except Exception:
                    pass

    def _notify_desktop(self, title, message):
        """Send a desktop notification if plyer is available."""
        try:
            from plyer import notification
            notification.notify(
                title=title,
                message=message,
                app_name='Robinhood Monitor',
                timeout=8,
            )
        except Exception:
            pass  # plyer not available or notification failed

    # ── Session validation ────────────────────────────────────────────────────

    def _is_session_error(self, err_str):
        """Return True if the error indicates the robin_stocks session is broken."""
        markers = ['can only be called when logged in', 'not logged in',
                   'login required', 'token', 'unauthorized']
        return any(m in err_str.lower() for m in markers)

    def _handle_session_error(self, e):
        """Reset auth state so the overlay re-appears on the next poll."""
        self._logged_in   = False
        self.auth_status  = 'error'
        self.auth_message = 'Session expired — please retry login.'
        logger.error(f"Session error detected: {e}")
        self._notify_desktop("Robinhood Session Expired",
                             "Open the dashboard and click Retry to reconnect.")

    # ── Positions ─────────────────────────────────────────────────────────────

    def get_options_positions(self):
        try:
            import robin_stocks.robinhood as rh
            positions = rh.options.get_open_option_positions() or []
            result = []
            for pos in positions:
                if not pos:
                    continue
                quantity = float(pos.get('quantity', 0))
                if quantity == 0:
                    continue
                option_id = pos.get('option_id', '')
                option_data = self._fetch_option_data(rh, option_id, pos.get('option', ''))
                if not option_data:
                    logger.warning(f"Skipping position {option_id} - could not get option details")
                    continue
                result.append({
                    'id':              option_id,
                    'symbol':          pos.get('chain_symbol', '').upper(),
                    'type':            option_data.get('type', 'unknown'),
                    'strike_price':    float(option_data.get('strike_price', 0)),
                    'expiration_date': option_data.get('expiration_date', ''),
                    'quantity':        quantity,
                    'average_price':   float(pos.get('average_price', 0)) / 100,
                    'position_type':   pos.get('type', 'long'),
                })
            logger.info(f"Fetched {len(result)} open options positions")
            return result
        except Exception as e:
            if self._is_session_error(str(e)):
                self._handle_session_error(e)
            else:
                logger.error(f"Error fetching options positions: {e}")
            return []

    def _fetch_option_data(self, rh, option_id, option_url):
        if option_id:
            try:
                data = rh.options.get_option_instrument_data_by_id(option_id)
                if data and data.get('strike_price'):
                    return data
            except Exception:
                pass
        if option_url:
            try:
                data = rh.helper.request_get(option_url)
                if data and data.get('strike_price'):
                    return data
            except Exception:
                pass
        return None

    # ── Prices ────────────────────────────────────────────────────────────────

    def get_stock_price(self, symbol):
        try:
            import robin_stocks.robinhood as rh
            prices = rh.stocks.get_latest_price(symbol, includeExtendedHours=True)
            if prices and prices[0]:
                return float(prices[0])
        except Exception as e:
            logger.warning(f"Robinhood price fetch failed for {symbol}: {e}")
        try:
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            data = ticker.history(period='1d', interval='1m')
            if not data.empty:
                price = float(data['Close'].iloc[-1])
                logger.info(f"Used yfinance fallback for {symbol}: ${price:.2f}")
                return price
        except Exception as e:
            logger.warning(f"yfinance fallback also failed for {symbol}: {e}")
        return None

    def get_prices_batch(self, symbols):
        try:
            import robin_stocks.robinhood as rh
            prices = rh.stocks.get_latest_price(symbols, includeExtendedHours=True)
            return {sym: float(p) for sym, p in zip(symbols, prices) if p}
        except Exception as e:
            logger.warning(f"Batch price fetch failed: {e}. Falling back to individual lookups.")
            return {sym: self.get_stock_price(sym) for sym in symbols}

    # ── Account / Cash ────────────────────────────────────────────────────────

    def get_account_cash_info(self):
        """
        Fetch cash, buying power, and withdrawable cash from Robinhood.

        Buying power note: Robinhood Instant/Gold accounts show margin-enhanced
        buying power in the app. The correct figure comes from
        margin_balances.overnight_buying_power, which matches what the app displays.
        We fall back to profile.buying_power for cash accounts.

        Fields returned:
          cash_available_for_withdrawal - money you can actually withdraw today
          buying_power                  - matches what Robinhood app shows
          cash                          - total cash balance
          cash_held_for_orders          - reserved for pending orders
          uncleared_deposits            - deposits still settling
          portfolio_equity              - total portfolio value (cash + positions)
        """
        try:
            import robin_stocks.robinhood as rh

            def _f(val):
                try:
                    return float(val or 0)
                except (TypeError, ValueError):
                    return 0.0

            profile   = rh.account.load_account_profile()   or {}
            portfolio = rh.account.load_portfolio_profile() or {}

            # Robinhood Instant/Gold: the app's displayed buying power comes from
            # margin_balances.overnight_buying_power for Gold accounts.
            # For basic Instant accounts the margin_balances dict may be empty/null.
            # Guard against the case where robin_stocks returns a URL string instead
            # of an expanded dict for margin_balances.
            raw_margin   = profile.get('margin_balances')
            margin       = raw_margin if isinstance(raw_margin, dict) else {}
            direct_bp    = _f(profile.get('buying_power'))
            overnight_bp = _f(margin.get('overnight_buying_power') or
                               margin.get('overnight_buying_power_for_option_regulars'))
            day_trade_bp = _f(margin.get('day_trade_buying_power') or
                               margin.get('day_trade_buying_power_for_option_regulars'))
            margin_limit = _f(margin.get('margin_limit'))

            # buying_power_with_margin: the best "full" BP we can find.
            # Prefer overnight_bp if non-zero, else day_trade_bp, else direct_bp.
            # We do NOT cap at direct_bp — if overnight < direct (unusual) we still
            # surface the raw value so the user can see a real difference.
            bp_with_margin = overnight_bp or day_trade_bp or direct_bp
            has_margin     = bp_with_margin != direct_bp

            logger.info(
                f"BP — cash/direct: ${direct_bp:.2f}  overnight: ${overnight_bp:.2f}  "
                f"day_trade: ${day_trade_bp:.2f}  margin_limit: ${margin_limit:.2f}  "
                f"has_margin_diff: {has_margin}"
            )

            info = {
                'cash':                          _f(profile.get('cash')),
                'cash_available_for_withdrawal': _f(profile.get('cash_available_for_withdrawal')),
                'buying_power':                  direct_bp,
                'buying_power_with_margin':      bp_with_margin,
                'has_margin':                    has_margin,
                'margin_limit':                  margin_limit,
                'cash_held_for_orders':          _f(profile.get('cash_held_for_orders')),
                'uncleared_deposits':            _f(profile.get('uncleared_deposits')),
                'portfolio_equity':              _f(portfolio.get('equity')),
            }
            logger.info(
                f"Cash info - withdrawable: ${info['cash_available_for_withdrawal']:.2f}  "
                f"buying power (cash): ${info['buying_power']:.2f}  "
                f"buying power (w/ margin): ${info['buying_power_with_margin']:.2f}"
            )
            return info

        except Exception as e:
            if self._is_session_error(str(e)):
                self._handle_session_error(e)
            else:
                logger.error(f"Error fetching account cash info: {e}")
            return None

    # ── Stock holdings ────────────────────────────────────────────────────────

    def get_owned_stock_symbols(self):
        """Return set of tickers where user holds shares. Used for covered call detection."""
        try:
            import robin_stocks.robinhood as rh
            positions = rh.account.get_open_stock_positions() or []
            symbols = set()
            for pos in positions:
                quantity = float(pos.get('quantity', 0))
                if quantity <= 0:
                    continue
                instrument_url = pos.get('instrument', '')
                if not instrument_url:
                    continue
                try:
                    data = rh.helper.request_get(instrument_url)
                    sym = (data or {}).get('symbol', '').upper()
                    if sym:
                        symbols.add(sym)
                except Exception:
                    pass
            logger.info(f"Owned stocks: {symbols or 'none'}")
            return symbols
        except Exception as e:
            logger.warning(f"Could not fetch stock positions: {e}")
            return set()

    # ── Bank Transfers ─────────────────────────────────────────────────────────

    def get_bank_transfers(self):
        """
        Fetch all bank transfers from Robinhood.
        Returns a list of normalised dicts:
          rh_id, transfer_date, amount, direction, status, notes
        """
        try:
            import robin_stocks.robinhood as rh
            raw = rh.account.get_bank_transfers() or []
            result = []
            for t in raw:
                if not t:
                    continue
                try:
                    amount    = float(t.get('amount') or 0)
                    direction = (t.get('direction') or 'deposit').lower()
                    # Robinhood states: pending, completed, failed, cancelled, reversed
                    state     = (t.get('state') or 'pending').lower()
                    if state in ('completed', 'cleared', 'returned'):
                        status = 'cleared'
                    elif state in ('failed', 'cancelled', 'reversed'):
                        status = 'cancelled'
                    else:
                        status = 'pending'
                    created   = t.get('created_at') or ''
                    date_str  = created[:10] if created else ''
                    rh_id     = t.get('id') or ''
                    early_amt = t.get('early_access_amount') or ''
                    notes     = f"Robinhood transfer" + (f" (early access: ${early_amt})" if early_amt else '')
                    if amount > 0 and rh_id:
                        result.append({
                            'rh_id':         rh_id,
                            'transfer_date': date_str,
                            'amount':        amount,
                            'direction':     direction,
                            'status':        status,
                            'notes':         notes,
                        })
                except Exception as inner_e:
                    logger.debug(f"Skipping transfer row: {inner_e}")
            logger.info(f"Fetched {len(result)} bank transfers from Robinhood")
            return result
        except Exception as e:
            logger.warning(f"Could not fetch bank transfers: {e}")
            return []

    # ── Options Income History ────────────────────────────────────────────────

    def get_options_order_history(self):
        """
        Fetch all filled options orders from Robinhood.
        Returns a list of normalised dicts ready for the options_income table.

        net_premium sign convention:
          credit orders (sell to open / buy to close that nets credit) → positive
          debit  orders (buy to open / buy to close at a cost)         → negative
        """
        try:
            import robin_stocks.robinhood as rh
            raw = rh.orders.get_all_option_orders() or []
            result = []
            for order in raw:
                if not order:
                    continue
                state = (order.get('state') or '').lower()
                if state != 'filled':
                    continue
                try:
                    processed_premium = float(order.get('processed_premium') or 0)
                    direction         = (order.get('direction') or 'debit').lower()
                    net_premium = processed_premium if direction == 'credit' else -processed_premium

                    created_at = order.get('created_at') or ''
                    order_date = created_at[:10] if created_at else ''

                    legs = order.get('legs') or [{}]
                    leg  = legs[0] if legs else {}

                    option_url  = leg.get('option') or ''
                    option_data = {}
                    if option_url:
                        try:
                            option_data = rh.helper.request_get(option_url) or {}
                        except Exception:
                            pass

                    result.append({
                        'rh_order_id':       order.get('id', ''),
                        'symbol':            order.get('chain_symbol', '').upper(),
                        'option_type':       option_data.get('type') or leg.get('option_type', ''),
                        'strike_price':      float(option_data.get('strike_price') or 0),
                        'expiration_date':   option_data.get('expiration_date') or '',
                        'opening_strategy':  order.get('opening_strategy') or '',
                        'closing_strategy':  order.get('closing_strategy') or '',
                        'direction':         direction,
                        'quantity':          float(order.get('processed_quantity') or
                                                   order.get('quantity') or 0),
                        'processed_premium': processed_premium,
                        'net_premium':       round(net_premium, 2),
                        'order_date':        order_date,
                        'state':             state,
                    })
                except Exception as inner_e:
                    logger.debug(f"Skipping options order: {inner_e}")

            logger.info(f"Fetched {len(result)} filled options orders")
            return result
        except Exception as e:
            logger.error(f"Error fetching options order history: {e}")
            return []

    def sync_options_income_to_db(self):
        """
        Sync all filled options orders into the options_income table.
        Uses INSERT OR IGNORE — safe to call repeatedly.
        Returns count of orders processed.
        """
        from database import upsert_options_income
        orders = self.get_options_order_history()
        for o in orders:
            upsert_options_income(
                rh_order_id      = o['rh_order_id'],
                symbol           = o['symbol'],
                option_type      = o['option_type'],
                strike_price     = o['strike_price'],
                expiration_date  = o['expiration_date'],
                opening_strategy = o['opening_strategy'],
                closing_strategy = o['closing_strategy'],
                direction        = o['direction'],
                quantity         = o['quantity'],
                processed_premium= o['processed_premium'],
                net_premium      = o['net_premium'],
                order_date       = o['order_date'],
                state            = o['state'],
            )
        logger.info(f"Synced {len(orders)} options income records to DB")
        return len(orders)

    def sync_transfers_to_db(self):
        """
        Fetch bank transfers from Robinhood and upsert into the local DB.
        Returns number of rows added/updated.
        """
        from database import upsert_transfer_by_rhid
        transfers = self.get_bank_transfers()
        for t in transfers:
            upsert_transfer_by_rhid(
                rh_id         = t['rh_id'],
                transfer_date = t['transfer_date'],
                amount        = t['amount'],
                direction     = t['direction'],
                status        = t['status'],
                notes         = t['notes'],
            )
        return len(transfers)
