@echo off
title Robinhood Options Monitor
color 0A

echo.
echo  ============================================================
echo    Robinhood Options Monitor
echo  ============================================================
echo.

:: Navigate to the monitor folder
cd /d "%~dp0robinhood_monitor"

:: Check that .env exists
if not exist ".env" (
    echo  [ERROR] .env file not found!
    echo.
    echo  Please copy .env.template to .env and fill in your
    echo  Robinhood username and password.
    echo.
    echo  File location: %~dp0robinhood_monitor\.env
    echo.
    pause
    exit /b 1
)

:: Install / upgrade Python packages (only runs if missing)
echo  Checking Python packages...
pip install -r requirements.txt --quiet --disable-pip-version-check
if errorlevel 1 (
    echo.
    echo  [ERROR] Failed to install packages.
    echo  Make sure Python is installed: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

echo.
echo  Starting monitor... the dashboard will open in your browser.
echo  Press Ctrl+C to stop.
echo.

:: Launch the Flask app (it opens the browser automatically)
python app.py

pause
