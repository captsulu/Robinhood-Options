# Robinhood Options Monitor – Setup Guide

## What This Does

Monitors all open options positions in your Robinhood account and:
- Fetches live stock prices every 5 minutes during market hours (4 AM – 8 PM ET, weekdays)
- Alerts you via desktop notification and/or email when any option's underlying price
  comes within **5%** of the strike price (adjustable)
- Warns you specifically when expiration is **≤ 2 days away** and price is in the danger zone
- Logs all price history and displays live charts in your browser at **http://localhost:5000**

---

## Step 1 – Install Python (if not already installed)

1. Go to https://www.python.org/downloads/
2. Download and install Python 3.10 or newer
3. **Important:** Check "Add Python to PATH" during installation

---

## Step 2 – Set Up Your Credentials

1. Open the `robinhood_monitor` folder
2. Find the file named `.env.template`
3. Copy it and rename the copy to just `.env` (no ".template")
4. Open `.env` in Notepad and fill in your Robinhood email and password:

```
ROBINHOOD_USERNAME=youremail@example.com
ROBINHOOD_PASSWORD=yourpassword
```

5. Save and close the file

> **Note:** Your credentials are stored only on your computer in this file.
> They are never sent anywhere except directly to Robinhood's login API.

---

## Step 3 – Run the Monitor

Double-click `start_robinhood_monitor.bat` in the `Trading` folder.

The first launch will install Python packages automatically (takes ~30 seconds).
Your browser will open to **http://localhost:5000** when everything is ready.

---

## Step 4 – (Optional) Set Up Email Alerts

Email uses Gmail with an App Password (different from your regular password).

### Create a Gmail App Password:
1. Go to https://myaccount.google.com/security
2. Make sure 2-Step Verification is ON
3. Search for "App passwords" and click it
4. Create a new app password → choose "Mail" and "Windows Computer"
5. Copy the 16-character password shown

### Enter it in config.json:
Open `robinhood_monitor/config.json` and update the `email` section:

```json
"email": {
  "enabled": true,
  "smtp_server": "smtp.gmail.com",
  "smtp_port": 587,
  "from_address": "captsulu@gmail.com",
  "to_address": "captsulu@gmail.com",
  "app_password": "xxxx xxxx xxxx xxxx"
}
```

---

## Adjusting the Tolerance

You can change the tolerance (default 5%) two ways:

**Option A – In the browser dashboard:**
Click the ⚙ Settings button at the top right, drag the slider, and click Save.

**Option B – In config.json directly:**
```json
"tolerance_percent": 5.0
```
Change `5.0` to any value (e.g. `3.0` for tighter alerts, `10.0` for wider).

---

## Alert Logic

| Condition | Status |
|-----------|--------|
| Price already past the strike (ITM for short) | 🚨 **CRITICAL** |
| Price within tolerance % of strike AND ≤ 2 DTE | 🚨 **CRITICAL** |
| Price within tolerance % of strike | ⚠️ **WARNING** |
| Near expiry but not yet in tolerance zone | ⚠️ **WARNING** |
| All clear | ✅ **SAFE** |

> **DTE** = Days To Expiration

---

## Auto-Start with Windows (Optional)

To have the monitor start automatically when you log in to Windows:

1. Press `Win + R`, type `shell:startup`, press Enter
2. Create a shortcut to `start_robinhood_monitor.bat` in that folder

---

## Files Reference

| File | Purpose |
|------|---------|
| `app.py` | Flask web server + background monitor thread |
| `monitor.py` | Core scan logic (prices, risk math, alerts) |
| `robinhood_client.py` | Robinhood API wrapper (robin_stocks) |
| `database.py` | SQLite price logging |
| `alerts.py` | Desktop + email notification dispatch |
| `config_manager.py` | Read/write config.json |
| `config.json` | All settings (tolerance, email, scan interval) |
| `.env` | Your Robinhood credentials (keep private!) |
| `monitor.db` | SQLite database (auto-created) |
| `monitor.log` | Log file for troubleshooting |

---

## Troubleshooting

**"Robinhood login failed"**
- Check your username/password in `.env`
- Make sure there's no trailing space after the password
- Try logging in to robinhood.com to confirm credentials work

**"No open options positions found"**
- The monitor only shows open positions (not closed/expired ones)
- Confirm you have open options in your Robinhood account

**Charts show no data**
- Charts fill in as price history is collected – check back after a few scans
- The monitor only runs during 4 AM – 8 PM ET on weekdays

**Desktop notifications not appearing**
- Make sure plyer is installed: `pip install plyer --break-system-packages`
- Check Windows notification settings (Settings → System → Notifications)
