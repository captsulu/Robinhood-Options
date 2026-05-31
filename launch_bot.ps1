# ============================================================
#  eTrade Cash-Secured Puts Bot  |  Launcher Script
#
#  Credentials are now loaded automatically from your .env file.
#  No more pasting keys at runtime!
#
#  FIRST-TIME SETUP:
#    1. In your Trading folder, find the file:  .env.example
#    2. Make a copy of it and rename the copy to exactly:  .env
#    3. Open .env in Notepad and fill in your two Sandbox keys
#    4. Save and close — you only do this once
#
#  HOW TO RUN (after setup):
#    1. Open PowerShell
#    2. Navigate to this folder:
#         cd "C:\path\to\your\Trading folder"
#    3. Run:
#         .\launch_bot.ps1
#
#    (If PowerShell blocks the script, run this once first:
#         Set-ExecutionPolicy -Scope CurrentUser RemoteSigned )
# ============================================================

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  eTrade Cash-Secured Puts Bot  |  Paper Trading Mode" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# ── Locate files ────────────────────────────────────────────────────────────

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$envFile   = Join-Path $scriptDir ".env"
$botScript = Join-Path $scriptDir "cash_secured_puts_bot.py"

# ── Check .env file exists ───────────────────────────────────────────────────

if (-not (Test-Path $envFile)) {
    Write-Host "  ❌ No .env file found in this folder." -ForegroundColor Red
    Write-Host ""
    Write-Host "  To fix this:" -ForegroundColor Yellow
    Write-Host "    1. Find the file '.env.example' in your Trading folder" -ForegroundColor Yellow
    Write-Host "    2. Make a copy and rename the copy to '.env'" -ForegroundColor Yellow
    Write-Host "    3. Open '.env' in Notepad and fill in your Sandbox keys" -ForegroundColor Yellow
    Write-Host "    4. Run this launcher again" -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

# ── Verify .env has the required keys (without reading their values) ─────────

$envContent = Get-Content $envFile -Raw

$hasKey    = $envContent -match "SANDBOX_CONSUMER_KEY\s*=\s*\S+"
$hasSecret = $envContent -match "SANDBOX_CONSUMER_SECRET\s*=\s*\S+"

if (-not $hasKey -or -not $hasSecret) {
    Write-Host "  ❌ Your .env file is missing one or both keys." -ForegroundColor Red
    Write-Host ""
    Write-Host "  Make sure your .env file contains both of these lines" -ForegroundColor Yellow
    Write-Host "  with your actual Sandbox values (not the placeholder text):" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "    SANDBOX_CONSUMER_KEY=your_actual_key_here" -ForegroundColor White
    Write-Host "    SANDBOX_CONSUMER_SECRET=your_actual_secret_here" -ForegroundColor White
    Write-Host ""
    exit 1
}

Write-Host "  ✅ .env file found and keys are present." -ForegroundColor Green
Write-Host ""

# ── Check Python is installed ────────────────────────────────────────────────

$pythonCmd = $null
foreach ($cmd in @("python", "python3")) {
    try {
        $version = & $cmd --version 2>&1
        if ($version -match "Python 3") {
            $pythonCmd = $cmd
            break
        }
    } catch {}
}

if ($null -eq $pythonCmd) {
    Write-Host "  ❌ Python 3 not found." -ForegroundColor Red
    Write-Host "  Install from https://www.python.org/downloads/" -ForegroundColor Red
    Write-Host "  Check 'Add Python to PATH' during installation." -ForegroundColor Red
    Write-Host ""
    exit 1
}

Write-Host "  ✅ Python found: $version" -ForegroundColor Green

# ── Check / install required libraries ──────────────────────────────────────

Write-Host "  Checking required libraries..." -ForegroundColor Yellow

$libCheck = & $pythonCmd -c "import rauth, requests, yfinance, dotenv; print('OK')" 2>&1

if ($libCheck -ne "OK") {
    Write-Host "  Installing missing libraries..." -ForegroundColor Yellow
    Write-Host ""
    $reqFile = Join-Path $scriptDir "requirements.txt"
    if (Test-Path $reqFile) {
        & $pythonCmd -m pip install -r $reqFile
    } else {
        & $pythonCmd -m pip install rauth requests yfinance python-dotenv
    }

    $libCheck = & $pythonCmd -c "import rauth, requests, yfinance, dotenv; print('OK')" 2>&1
    if ($libCheck -ne "OK") {
        Write-Host ""
        Write-Host "  ❌ Could not install libraries automatically." -ForegroundColor Red
        Write-Host "  Run manually:  pip install rauth requests yfinance python-dotenv" -ForegroundColor Red
        exit 1
    }
}

Write-Host "  ✅ All libraries ready." -ForegroundColor Green
Write-Host ""

# ── Check bot script exists ──────────────────────────────────────────────────

if (-not (Test-Path $botScript)) {
    Write-Host "  ❌ cash_secured_puts_bot.py not found in this folder." -ForegroundColor Red
    exit 1
}

# ── Launch the bot ───────────────────────────────────────────────────────────

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Starting bot...  (credentials load from .env silently)" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

& $pythonCmd $botScript

Write-Host ""
Write-Host "  Session ended." -ForegroundColor DarkGray
Write-Host ""
