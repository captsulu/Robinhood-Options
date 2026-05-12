"""
Configuration management for the Options Monitor.
Reads/writes config.json in the same directory as this script.
"""

import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')

DEFAULT_CONFIG = {
    "tolerance_percent": 2.0,
    "days_before_expiration_warning": 3,
    "scan_interval_minutes": 5,
    "desktop_notifications": True,
    "email": {
        "enabled": False,
        "smtp_server": "smtp.gmail.com",
        "smtp_port": 587,
        "from_address": "captsulu@gmail.com",
        "to_address": "captsulu@gmail.com",
        "app_password": "YOUR_GMAIL_APP_PASSWORD_HERE"
    },
    "market_hours": {
        "premarket_start": "04:00",
        "aftermarket_end": "20:00",
        "timezone": "America/New_York"
    }
}


def load_config():
    """Load config from disk, filling in defaults for any missing keys."""
    if not os.path.exists(CONFIG_PATH):
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()

    with open(CONFIG_PATH, 'r') as f:
        config = json.load(f)

    # Fill in any missing top-level keys from defaults
    for key, val in DEFAULT_CONFIG.items():
        if key not in config:
            config[key] = val

    return config


def save_config(config):
    """Save config to disk."""
    with open(CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=2)
