"""
================================================================================
  CASH-SECURED PUTS BOT  |  eTrade Paper Trading (Sandbox)
================================================================================

WHAT IS A CASH-SECURED PUT?
  - You sell a put option on a stock you wouldn't mind owning.
  - The buyer pays you a PREMIUM upfront (this is your income).
  - If the stock stays ABOVE your strike price at expiration → you keep the premium. Done.
  - If the stock drops BELOW your strike price → you buy 100 shares at the strike price.
    (That's okay because you only pick stocks you'd be happy to own.)

RISK:
  - You need enough CASH in your account to buy 100 shares at the strike price.
  - Example: Strike = $50, you need $5,000 in cash reserved per contract.
  - This script checks your cash before placing any order.

HOW TO USE THIS SCRIPT:
  1. Complete Step 1 (get your eTrade API Sandbox keys).
  2. Install Python dependencies (see requirements.txt).
  3. Run this script: python cash_secured_puts_bot.py
  4. Follow the prompts.

Author: Built for Greg | eTrade Sandbox / Paper Trading ONLY
================================================================================
"""

# ── IMPORTS ──────────────────────────────────────────────────────────────────
# These are libraries (toolkits) that give us extra abilities.

import webbrowser       # Opens your browser automatically for login
import json             # Reads/writes data in JSON format (like a structured text file)
import os               # Interacts with your file system (saving/loading tokens)
import sys              # Lets us exit the script cleanly if something goes wrong
from datetime import datetime, timedelta  # Works with dates and times

# rauth handles the OAuth login process (how eTrade proves it's really you)
# requests handles sending/receiving data over the internet
# yfinance pulls live market data and options chains from Yahoo Finance
# dotenv loads credentials from the .env file automatically
try:
    import requests
    from rauth import OAuth1Service
    from dotenv import load_dotenv
except ImportError:
    print("\n❌ Missing required libraries.")
    print("   Please run:  pip install rauth requests yfinance python-dotenv")
    sys.exit(1)

# Load the .env file from the same folder as this script.
# This makes SANDBOX_CONSUMER_KEY and SANDBOX_CONSUMER_SECRET available
# via os.environ without you having to type them every time.
_script_dir = os.path.dirname(os.path.abspath(__file__))
_env_path   = os.path.join(_script_dir, ".env")
load_dotenv(dotenv_path=_env_path)

# Import the auto-scanner module (scanner.py must be in the same folder)
try:
    import scanner as sc
    SCANNER_AVAILABLE = True
except ImportError:
    SCANNER_AVAILABLE = False


# ── CONFIGURATION ─────────────────────────────────────────────────────────────
# ⚠️  SANDBOX ONLY - These are paper trading credentials, NOT real money

SANDBOX_BASE_URL   = "https://apisb.etrade.com"  # Sandbox (paper) API endpoint
LIVE_BASE_URL      = "https://api.etrade.com"     # Live API - DO NOT USE YET

# Token file: saves your login session so you don't have to log in every time
TOKEN_FILE = "etrade_tokens.json"


# ── RISK SETTINGS ─────────────────────────────────────────────────────────────
# Adjust these to control how aggressive or conservative the bot is.

MAX_DAYS_TO_EXPIRATION   = 21    # Only look at options expiring within 21 days
MIN_DAYS_TO_EXPIRATION   = 7     # Don't go shorter than 7 days (too fast-moving)
TARGET_DELTA             = 0.30  # Aim for puts with ~30% chance of being assigned
                                 # (0.30 delta = roughly 30% chance stock hits strike)
MAX_RISK_PER_TRADE       = 0.10  # Never risk more than 10% of account cash on one trade
MIN_PREMIUM_DOLLARS      = 0.50  # Only sell puts that pay at least $0.50/share ($50/contract)


# ── PART 1: AUTHENTICATION ────────────────────────────────────────────────────
# This section handles logging into eTrade via the API.

def get_credentials():
    """
    Loads eTrade Sandbox API keys from the .env file (preferred) or
    falls back to manual entry if the .env file is missing or incomplete.

    Priority order:
      1. SANDBOX_CONSUMER_KEY / SANDBOX_CONSUMER_SECRET from .env file
      2. ETRADE_CONSUMER_KEY / ETRADE_CONSUMER_SECRET from PowerShell launcher
      3. Manual input prompt (last resort)

    To set up the .env file:
      - Copy .env.example → rename it to .env
      - Fill in your Sandbox Consumer Key and Secret
      - Save — done. You'll never need to paste them again.
    """
    # Priority 1: .env file (loaded automatically by load_dotenv above)
    consumer_key    = os.environ.get("SANDBOX_CONSUMER_KEY", "").strip()
    consumer_secret = os.environ.get("SANDBOX_CONSUMER_SECRET", "").strip()

    if consumer_key and consumer_secret:
        print("\n✅ Credentials loaded from .env file.")
        return consumer_key, consumer_secret

    # Priority 2: PowerShell launcher environment variables (legacy fallback)
    consumer_key    = os.environ.get("ETRADE_CONSUMER_KEY", "").strip()
    consumer_secret = os.environ.get("ETRADE_CONSUMER_SECRET", "").strip()

    if consumer_key and consumer_secret:
        print("\n✅ Credentials loaded from PowerShell launcher.")
        return consumer_key, consumer_secret

    # Priority 3: Manual input — .env file not found or incomplete
    print("\n" + "="*60)
    print("  eTrade API Login")
    print("="*60)
    print("\n⚠️  No .env file found (or it's missing the keys).")
    print("   For easier logins, copy .env.example → .env and fill it in.")
    print("\nManual entry — enter your Sandbox credentials below:")
    print("(from developer.etrade.com — NOT your regular eTrade login)\n")

    consumer_key    = input("  Sandbox Consumer Key:    ").strip()
    consumer_secret = input("  Sandbox Consumer Secret: ").strip()

    if not consumer_key or not consumer_secret:
        print("\n❌ Both fields are required. Please check your developer portal.")
        sys.exit(1)

    return consumer_key, consumer_secret


def login_to_etrade(consumer_key, consumer_secret):
    """
    Walks through the OAuth login process with eTrade.
    OAuth is a secure way to prove your identity without sharing your password with our script.

    Steps:
      1. We request a temporary token from eTrade.
      2. We open your browser so you can log in directly on eTrade's website.
      3. eTrade gives you a verification code (verifier).
      4. We exchange that for a permanent access token.
    """
    print("\n📡 Connecting to eTrade Sandbox...")

    # Set up the OAuth service with eTrade's URLs
    etrade_oauth = OAuth1Service(
        name             = "etrade",
        consumer_key     = consumer_key,
        consumer_secret  = consumer_secret,
        request_token_url= f"{SANDBOX_BASE_URL}/oauth/request_token",
        access_token_url = f"{SANDBOX_BASE_URL}/oauth/access_token",
        authorize_url    = "https://us.etrade.com/e/t/etws/authorize",
        base_url         = SANDBOX_BASE_URL
    )

    # Step 1: Get a temporary request token
    try:
        request_token, request_token_secret = etrade_oauth.get_request_token(
            params={"oauth_callback": "oob", "format": "json"}
        )
    except Exception as e:
        print(f"\n❌ Could not connect to eTrade. Check your keys and internet connection.")
        print(f"   Error: {e}")
        sys.exit(1)

    # Step 2: Build the login URL and open it in the browser
    authorize_url = f"https://us.etrade.com/e/t/etws/authorize?key={consumer_key}&token={request_token}"
    print(f"\n🌐 Opening your browser to log in to eTrade...")
    print(f"   (If it doesn't open, paste this URL into your browser manually:)")
    print(f"   {authorize_url}\n")
    webbrowser.open(authorize_url)

    # Step 3: Ask for the verification code eTrade displays after login
    print("After logging in on eTrade's website, you'll see a verification code.")
    verifier = input("  Paste the verification code here: ").strip()

    # Step 4: Exchange the verifier for a real access token
    try:
        session = etrade_oauth.get_auth_session(
            request_token,
            request_token_secret,
            params={"oauth_verifier": verifier}
        )
    except Exception as e:
        print(f"\n❌ Login failed. The verification code may have expired (they're only valid for 5 minutes).")
        print(f"   Try running the script again. Error: {e}")
        sys.exit(1)

    print("\n✅ Successfully logged in to eTrade Sandbox!\n")
    return session


# ── PART 2: ACCOUNT INFORMATION ───────────────────────────────────────────────

def get_account_info(session):
    """
    Fetches a list of your eTrade accounts and lets you pick one.
    Returns the account ID key needed for all other API calls.
    """
    print("📊 Fetching your accounts...")

    url = f"{SANDBOX_BASE_URL}/v1/accounts/list.json"
    response = session.get(url, params={"format": "json"})

    if response.status_code != 200:
        print(f"❌ Could not fetch accounts. Status: {response.status_code}")
        print(f"   Response: {response.text}")
        sys.exit(1)

    data = response.json()

    # Navigate the nested JSON structure eTrade returns
    accounts = data.get("AccountListResponse", {}).get("Accounts", {}).get("Account", [])

    if not accounts:
        print("❌ No accounts found. Make sure your paper trading account is active.")
        sys.exit(1)

    # Display accounts so Greg can pick the right one
    print("\n  Your eTrade Accounts:")
    print("  " + "-"*40)
    for i, acct in enumerate(accounts):
        acct_id   = acct.get("accountId", "Unknown")
        acct_desc = acct.get("accountDesc", "No description")
        acct_mode = acct.get("accountMode", "")
        print(f"  [{i+1}] {acct_desc} | ID: {acct_id} | Mode: {acct_mode}")

    print()
    choice = input("  Which account do you want to use? Enter the number: ").strip()

    try:
        selected = accounts[int(choice) - 1]
    except (ValueError, IndexError):
        print("❌ Invalid selection.")
        sys.exit(1)

    account_id_key = selected.get("accountIdKey")
    print(f"\n✅ Using account: {selected.get('accountDesc')}")
    return account_id_key


def get_available_cash(session, account_id_key):
    """
    Checks how much cash is available in the paper trading account.
    For cash-secured puts, we need enough to cover 100 shares × strike price.
    """
    url = f"{SANDBOX_BASE_URL}/v1/accounts/{account_id_key}/balance.json"
    response = session.get(url, params={"format": "json", "instType": "BROKERAGE", "realTimeNAV": "true"})

    if response.status_code != 200:
        print(f"❌ Could not fetch balance. Status: {response.status_code}")
        return 0.0

    data = response.json()
    balance_data = data.get("BalanceResponse", {})
    cash_available = balance_data.get("Computed", {}).get("cashAvailableForInvestment", 0.0)

    print(f"\n💰 Cash Available for Trading: ${cash_available:,.2f}")
    return float(cash_available)


# ── PART 3: FINDING OPTIONS TO SELL ───────────────────────────────────────────

def get_option_chain(session, symbol, expiry_date):
    """
    Fetches the options chain for a given stock symbol and expiration date.
    An options chain is the full list of available put and call contracts.

    symbol:      Stock ticker, e.g. "AAPL"
    expiry_date: A datetime.date object for the expiration date
    """
    url = f"{SANDBOX_BASE_URL}/v1/market/optionchains.json"

    params = {
        "symbol"          : symbol,
        "expiryYear"      : expiry_date.year,
        "expiryMonth"     : expiry_date.month,
        "expiryDay"       : expiry_date.day,
        "optionCategory"  : "STANDARD",
        "chainType"       : "PUT",         # We only want PUTS for cash-secured puts
        "skipAdjusted"    : "true",
        "format"          : "json"
    }

    response = session.get(url, params=params)

    if response.status_code != 200:
        print(f"   ⚠️  Could not get options for {symbol}. Status: {response.status_code}")
        return []

    data = response.json()
    option_pairs = data.get("OptionChainResponse", {}).get("OptionPair", [])

    # Extract the Put side from each pair
    puts = []
    for pair in option_pairs:
        put = pair.get("Put", {})
        if put:
            puts.append(put)

    return puts


def find_good_puts(puts, current_stock_price, cash_available):
    """
    Filters the options chain to find puts worth selling.

    Rules we apply:
    1. The put must be OUT OF THE MONEY (strike below current stock price).
       Selling an in-the-money put is too risky for this strategy.
    2. The premium must be at least MIN_PREMIUM_DOLLARS per share.
    3. We must have enough cash to cover 100 shares at the strike price.
    4. We target puts with delta close to TARGET_DELTA (around 0.30).
    """
    good_puts = []
    max_cash_per_trade = cash_available * MAX_RISK_PER_TRADE

    for put in puts:
        try:
            strike     = float(put.get("strikePrice", 0))
            bid        = float(put.get("bid", 0))        # What buyers pay us
            ask        = float(put.get("ask", 0))        # What sellers ask
            delta_raw  = put.get("GreekValues", {}).get("delta", None)
            mid_price  = (bid + ask) / 2                 # We use the midpoint as estimate

            # Skip if we can't get a price
            if bid <= 0 or strike <= 0:
                continue

            # Rule 1: Must be out of the money
            if strike >= current_stock_price:
                continue

            # Rule 2: Premium must be worth it
            if mid_price < MIN_PREMIUM_DOLLARS:
                continue

            # Rule 3: Must have enough cash (100 shares × strike)
            cash_required = strike * 100
            if cash_required > max_cash_per_trade:
                continue

            # Calculate premium as % of strike (annualized return estimate)
            premium_yield = (mid_price / strike) * 100

            good_puts.append({
                "strike"        : strike,
                "bid"           : bid,
                "ask"           : ask,
                "mid"           : round(mid_price, 2),
                "delta"         : delta_raw,
                "cash_required" : cash_required,
                "premium_yield" : round(premium_yield, 2),
                "total_premium" : round(mid_price * 100, 2)   # Per contract (100 shares)
            })

        except (ValueError, TypeError):
            continue  # Skip any options with bad data

    # Sort by premium yield, best first
    good_puts.sort(key=lambda x: x["premium_yield"], reverse=True)
    return good_puts


def display_opportunities(symbol, puts, expiry_date):
    """Prints a clean table of put-selling opportunities for Greg to review."""
    if not puts:
        print(f"   No qualifying puts found for {symbol}.")
        return

    print(f"\n  📋 Put-Selling Opportunities: {symbol}  |  Expires: {expiry_date.strftime('%B %d, %Y')}")
    print("  " + "-"*70)
    print(f"  {'Strike':>8}  {'Bid':>6}  {'Ask':>6}  {'Mid':>6}  {'Cash Needed':>12}  {'Yield%':>7}  {'Per Contract':>12}")
    print("  " + "-"*70)

    for p in puts[:5]:  # Show top 5 to avoid overwhelming output
        print(f"  ${p['strike']:>7.2f}  "
              f"${p['bid']:>5.2f}  "
              f"${p['ask']:>5.2f}  "
              f"${p['mid']:>5.2f}  "
              f"${p['cash_required']:>10,.2f}  "
              f"{p['premium_yield']:>6.2f}%  "
              f"${p['total_premium']:>10.2f}")

    print()


# ── PART 4: PLACING THE TRADE ─────────────────────────────────────────────────

def place_put_order(session, account_id_key, symbol, strike, expiry_date, mid_price, quantity=1):
    """
    Places a SELL TO OPEN order for a cash-secured put in paper trading.

    SELL TO OPEN = we are the ones selling (writing) the option, not buying it.
    We collect premium immediately when the order fills.

    quantity: Number of contracts (1 contract = 100 shares).
              Start with 1 until you're comfortable.
    """

    # eTrade expects expiry as MMDDYYYY for the clientOrderId label
    expiry_str = expiry_date.strftime("%m%d%Y")

    # Use a safe strike string for the clientOrderId (no decimal point)
    strike_label = str(strike).replace(".", "_")

    # Build the order payload in the format eTrade requires.
    #
    # KEY RULES for SELL_OPEN (selling a put to collect premium):
    #   priceType  → NET_CREDIT  (we RECEIVE money, not pay it)
    #   limitPrice → the credit amount per share we want to collect
    #   allOrNone  → boolean false (not the string "false")
    #   quantity   → integer (not a string)
    #   strikePrice→ float  (not a string)
    #   expiryMonth/Day → integers, not strings
    #   stopPrice  → omitted entirely (not valid for limit orders)
    order_payload = {
        "PlaceOrderRequest": {
            "orderType"    : "OPTN",
            "clientOrderId": f"CSP_{symbol}_{expiry_str}_{strike_label}",
            "Order": [{
                "allOrNone"    : False,           # boolean, NOT the string "false"
                "priceType"    : "NET_CREDIT",    # SELL_OPEN = we receive a credit
                "orderTerm"    : "GOOD_FOR_DAY",
                "marketSession": "REGULAR",
                "limitPrice"   : round(float(mid_price), 2),
                "Instrument": [{
                    "Product": {
                        "securityType"  : "OPTN",
                        "symbol"        : symbol,
                        "callPut"       : "PUT",
                        "expiryYear"    : expiry_date.year,    # integer
                        "expiryMonth"   : expiry_date.month,   # integer
                        "expiryDay"     : expiry_date.day,     # integer
                        "strikePrice"   : float(strike),       # float, not string
                    },
                    "orderAction"  : "SELL_OPEN",
                    "quantityType" : "QUANTITY",
                    "quantity"     : int(quantity),            # integer, not string
                }]
            }]
        }
    }

    # Preview first (eTrade requires a preview before placing the actual order)
    preview_url = f"{SANDBOX_BASE_URL}/v1/accounts/{account_id_key}/orders/preview.json"
    preview_response = session.post(
        preview_url,
        json=order_payload,
        headers={"Content-Type": "application/json"}
    )

    if preview_response.status_code != 200:
        print(f"\n❌ Order preview failed. Status: {preview_response.status_code}")
        print(f"   Response: {preview_response.text[:500]}")
        return False

    preview_data   = preview_response.json()
    preview_id     = preview_data.get("PreviewOrderResponse", {}).get("PreviewIds", {}).get("previewId")
    estimated_cost = preview_data.get("PreviewOrderResponse", {}).get("Order", [{}])[0].get("estimatedTotalAmount", "N/A")

    print(f"\n  ✅ Order Preview Successful!")
    print(f"     Preview ID:       {preview_id}")
    print(f"     Estimated Credit: ${estimated_cost}")
    print(f"\n  ⚠️  This is PAPER TRADING. No real money is at risk.")

    confirm = input("\n  Place this paper trade? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("  Order cancelled.")
        return False

    # Add preview ID to payload and submit the real order
    order_payload["PlaceOrderRequest"]["PreviewIds"] = [{"previewId": preview_id}]

    place_url = f"{SANDBOX_BASE_URL}/v1/accounts/{account_id_key}/orders/place.json"
    place_response = session.post(
        place_url,
        json=order_payload,
        headers={"Content-Type": "application/json"}
    )

    if place_response.status_code == 200:
        order_data = place_response.json()
        order_id = order_data.get("PlaceOrderResponse", {}).get("OrderIds", {}).get("orderId", "Unknown")
        print(f"\n  🎉 Paper trade placed successfully!")
        print(f"     Order ID: {order_id}")
        print(f"     Premium collected (paper): ${mid_price * 100 * quantity:.2f}")
        return True
    else:
        print(f"\n❌ Order placement failed. Status: {place_response.status_code}")
        print(f"   Response: {place_response.text[:500]}")
        return False


# ── PART 5: VIEW OPEN POSITIONS ───────────────────────────────────────────────

def view_open_positions(session, account_id_key):
    """Shows all currently open options positions in the paper trading account."""
    url = f"{SANDBOX_BASE_URL}/v1/accounts/{account_id_key}/portfolio.json"
    response = session.get(url, params={"format": "json"})

    if response.status_code != 200:
        print(f"⚠️  Could not fetch positions. Status: {response.status_code}")
        return

    data      = response.json()
    accounts  = data.get("PortfolioResponse", {}).get("AccountPortfolio", [])

    print("\n📂 Open Positions:")
    print("  " + "-"*60)

    has_positions = False
    for acct in accounts:
        positions = acct.get("Position", [])
        for pos in positions:
            product   = pos.get("Product", {})
            sec_type  = product.get("securityType", "")

            if sec_type == "OPTN":   # Only show options positions
                has_positions = True
                symbol     = product.get("symbol", "")
                call_put   = product.get("callPut", "")
                strike     = product.get("strikePrice", "")
                expiry_mo  = product.get("expiryMonth", "")
                expiry_yr  = product.get("expiryYear", "")
                quantity   = pos.get("quantity", 0)
                cost_basis = pos.get("costBasis", 0)
                mkt_value  = pos.get("marketValue", 0)
                pnl        = pos.get("totalGain", 0)

                print(f"  {symbol} ${strike} {call_put} {expiry_mo}/{expiry_yr}  |  "
                      f"Qty: {quantity}  |  "
                      f"Cost: ${cost_basis:.2f}  |  "
                      f"MktVal: ${mkt_value:.2f}  |  "
                      f"P&L: ${pnl:.2f}")

    if not has_positions:
        print("  No open options positions found.")
    print()


# ── MAIN MENU ─────────────────────────────────────────────────────────────────

def main_menu(session, account_id_key, cash_available):
    """
    The main interactive menu. Greg can:
      1. Auto-scan via Barchart — finds the best put within $500 automatically
      2. Manual scan          — enter a specific ticker to search
      3. View open positions
      4. Exit
    """
    while True:
        print("\n" + "="*65)
        print("  CASH-SECURED PUTS BOT  |  Paper Trading Mode")
        print("="*65)
        print("  [1] 🤖 Auto-scan & recommend  (Barchart-powered, $500 budget)")
        print("  [2] 🔎 Manual scan             (enter your own ticker)")
        print("  [3] 📂 View my open positions")
        print("  [4] 🚪 Exit")
        print()

        choice = input("  Your choice: ").strip()

        # ── OPTION 1: AUTO-SCAN VIA BARCHART ──────────────────────────────────
        if choice == "1":
            if not SCANNER_AVAILABLE:
                print("\n  ❌ scanner.py not found in this folder.")
                print("     Make sure scanner.py is in the same directory as this script.")
                continue

            # Run the full auto-scan pipeline
            ranked = sc.auto_recommend(budget=500)

            if not ranked:
                continue

            # Ask if Greg wants to place the top recommendation as a paper trade
            print("  Would you like to place the #1 recommendation as a paper trade?")
            confirm = input("  (yes/no): ").strip().lower()

            if confirm == "yes":
                best = ranked[0]

                # Convert the expiration string to a datetime object for eTrade
                exp_date = datetime.strptime(best["expiration"], "%Y-%m-%d")

                print(f"\n  Placing paper trade:")
                print(f"  SELL 1x {best['symbol']} ${best['strike']:.2f} PUT  "
                      f"expiring {best['expiration']}  @ ${best['mid']:.2f}/share")
                print()

                place_put_order(
                    session,
                    account_id_key,
                    best["symbol"],
                    best["strike"],
                    exp_date,
                    best["mid"],
                    quantity=1
                )

        # ── OPTION 2: MANUAL SCAN (original behavior) ──────────────────────────
        elif choice == "2":
            symbol = input("\n  Enter stock ticker (e.g. AAPL, SPY, QQQ): ").strip().upper()
            if not symbol:
                continue

            # Get the current stock price via eTrade sandbox API
            quote_url  = f"{SANDBOX_BASE_URL}/v1/market/quote/{symbol}.json"
            quote_resp = session.get(quote_url, params={"format": "json"})

            if quote_resp.status_code != 200:
                print(f"❌ Could not get quote for {symbol}.")
                continue

            quote_data    = quote_resp.json()
            quote_details = quote_data.get("QuoteResponse", {}).get("QuoteData", [{}])[0]
            last_price    = quote_details.get("All", {}).get("lastTrade", 0)
            trade_time    = quote_details.get("All", {}).get("tradeTime", "")

            if not last_price:
                print(f"❌ Could not get price for {symbol}.")
                continue

            # Display symbol, price, and timestamp (as requested)
            ts_display = ""
            if trade_time:
                try:
                    ts_display = datetime.fromtimestamp(int(trade_time)).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                except Exception:
                    ts_display = str(trade_time)

            print(f"\n  {'SYMBOL':<8}  {'PRICE':<10}  TIMESTAMP")
            print("  " + "-"*45)
            print(f"  {symbol:<8}  ${last_price:<9.2f}  {ts_display}")

            # Look at expirations between MIN and MAX days out
            today = datetime.today()
            print(f"\n  Scanning options expiring in "
                  f"{MIN_DAYS_TO_EXPIRATION}–{MAX_DAYS_TO_EXPIRATION} days...")

            found_any = False
            for days_ahead in range(MIN_DAYS_TO_EXPIRATION, MAX_DAYS_TO_EXPIRATION + 1):
                candidate_date = today + timedelta(days=days_ahead)
                if candidate_date.weekday() == 4:   # Friday = weekly expiry
                    puts      = get_option_chain(session, symbol, candidate_date)
                    good_puts = find_good_puts(puts, last_price, cash_available)
                    if good_puts:
                        found_any = True
                        display_opportunities(symbol, good_puts, candidate_date)

                        trade = input("  Want to place a trade on one of these? (yes/no): ").strip().lower()
                        if trade == "yes":
                            print("\n  Enter the details from the table above:")
                            try:
                                chosen_strike = float(input("  Strike price: $").strip())
                                chosen_mid    = float(input("  Mid price: $").strip())
                                place_put_order(
                                    session, account_id_key, symbol,
                                    chosen_strike, candidate_date, chosen_mid,
                                    quantity=1
                                )
                            except ValueError:
                                print("❌ Invalid number entered.")

            if not found_any:
                print(f"\n  No qualifying opportunities found for {symbol}.")
                print(f"  Try a different stock, or use Option [1] for auto-scan.")

        # ── OPTION 3: VIEW POSITIONS ───────────────────────────────────────────
        elif choice == "3":
            view_open_positions(session, account_id_key)

        # ── OPTION 4: EXIT ────────────────────────────────────────────────────
        elif choice == "4":
            print("\n  👋 Goodbye! Remember: practice on paper before using real money.\n")
            break

        else:
            print("  Please enter 1, 2, 3, or 4.")


# ── ENTRY POINT ───────────────────────────────────────────────────────────────
# This runs when you execute:  python cash_secured_puts_bot.py

if __name__ == "__main__":
    print("\n" + "="*60)
    print("  CASH-SECURED PUTS BOT")
    print("  eTrade Sandbox (Paper Trading) - No Real Money")
    print("="*60)
    print("\n  ⚠️  IMPORTANT: This script uses PAPER TRADING only.")
    print("  It connects to eTrade's Sandbox environment.")
    print("  No real money will be risked.\n")

    # Step 1: Get credentials
    consumer_key, consumer_secret = get_credentials()

    # Step 2: Log in via OAuth
    session = login_to_etrade(consumer_key, consumer_secret)

    # Step 3: Choose the account
    account_id_key = get_account_info(session)

    # Step 4: Check available cash
    cash_available = get_available_cash(session, account_id_key)

    if cash_available < 500:
        print("\n⚠️  You have less than $500 in paper trading cash.")
        print("   You may need to reset your paper trading account balance on eTrade's website.")

    # Step 5: Launch the main menu
    main_menu(session, account_id_key, cash_available)
