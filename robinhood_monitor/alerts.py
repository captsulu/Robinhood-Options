"""
Alert dispatcher: sends desktop notifications and email alerts.
Email uses Gmail SMTP with an App Password (see SETUP.md for instructions).
"""

import logging
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config_manager import load_config

logger = logging.getLogger(__name__)

# Throttle: don't re-email the same position+status more than once per 2 hours
_last_email_time: dict = {}


def send_alert(status: str, symbol: str, message: str, position: dict):
    """
    Dispatch all configured alert channels for a triggered position.
    status  – 'warning' or 'critical'
    message – human-readable description
    position – enriched position dict (includes current_price, dte, etc.)
    """
    config = load_config()

    if config.get('desktop_notifications', True):
        _desktop(status, symbol, message)

    email_cfg = config.get('email', {})
    if email_cfg.get('enabled', False):
        throttle_key = f"{position.get('id', symbol)}_{status}"
        last = _last_email_time.get(throttle_key)
        now = datetime.now()
        if last is None or (now - last).total_seconds() > 7200:
            _email(status, symbol, message, position, email_cfg)
            _last_email_time[throttle_key] = now


# ── Desktop ───────────────────────────────────────────────────────────────────

def _desktop(status, symbol, message):
    title = f"{'🚨 CRITICAL' if status == 'critical' else '⚠️ WARNING'}: {symbol}"
    try:
        from plyer import notification
        notification.notify(
            title=title,
            message=message[:200],
            app_name="Options Monitor",
            timeout=12
        )
        logger.info(f"Desktop notification sent: {title}")
    except Exception as e:
        logger.warning(f"Desktop notification failed (plyer): {e}")
        # Windows-only fallback via PowerShell toast
        try:
            import subprocess
            ps_cmd = (
                f"[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
                f"ContentType = WindowsRuntime] | Out-Null; "
                f"$template = [Windows.UI.Notifications.ToastNotificationManager]"
                f"::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
                f"$template.SelectSingleNode('//text[@id=1]').InnerText = '{title}'; "
                f"$template.SelectSingleNode('//text[@id=2]').InnerText = 'Options Monitor Alert'; "
                f"[Windows.UI.Notifications.ToastNotificationManager]"
                f"::CreateToastNotifier('Options Monitor')"
                f".Show([Windows.UI.Notifications.ToastNotification]::new($template));"
            )
            subprocess.run(['powershell', '-Command', ps_cmd], capture_output=True, timeout=5)
        except Exception:
            pass  # Silent fail – dashboard still shows the alert


# ── Email ─────────────────────────────────────────────────────────────────────

def _email(status, symbol, message, position, email_cfg):
    from_addr  = email_cfg.get('from_address', '')
    to_addr    = email_cfg.get('to_address', '')
    app_pw     = email_cfg.get('app_password', '')
    smtp_host  = email_cfg.get('smtp_server', 'smtp.gmail.com')
    smtp_port  = int(email_cfg.get('smtp_port', 587))

    if not all([from_addr, to_addr, app_pw]) or app_pw == 'YOUR_GMAIL_APP_PASSWORD_HERE':
        logger.warning("Email not fully configured – skipping (see SETUP.md)")
        return

    color   = '#cc0000' if status == 'critical' else '#e67e00'
    label   = '🚨 CRITICAL ALERT' if status == 'critical' else '⚠️ WARNING'
    subject = f"Options Monitor {status.upper()}: {symbol} – Roll needed?"
    dist    = abs(position.get('distance_pct', 0))

    html = f"""
<html><body style="font-family:Arial,sans-serif;background:#0d1117;color:#e6edf3;padding:20px">
  <h2 style="color:{color}">{label}</h2>
  <table style="border-collapse:collapse;width:100%;max-width:500px">
    {''.join(f'<tr><td style="padding:8px;border:1px solid #30363d;color:#8b949e">{k}</td>'
             f'<td style="padding:8px;border:1px solid #30363d;font-weight:bold">{v}</td></tr>'
             for k, v in [
                 ('Symbol',            position.get('symbol', symbol)),
                 ('Option Type',       position.get('type', '').upper()),
                 ('Position',          position.get('position_type', '').upper()),
                 ('Strike Price',      f"${position.get('strike_price', 0):.2f}"),
                 ('Current Price',     f"${position.get('current_price', 0):.2f}"),
                 ('Distance to Strike',f"{dist:.1f}%"),
                 ('Days to Expiry',    str(position.get('dte', '?'))),
                 ('Expiration Date',   position.get('expiration_date', '?')),
             ])}
  </table>
  <p style="color:#8b949e;margin-top:20px">
    Consider rolling this position to avoid assignment.<br>
    <small>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S ET')}</small>
  </p>
</body></html>
"""

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From']    = from_addr
        msg['To']      = to_addr
        msg.attach(MIMEText(html, 'html'))

        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as srv:
            srv.starttls()
            srv.login(from_addr, app_pw)
            srv.sendmail(from_addr, to_addr, msg.as_string())

        logger.info(f"Email alert sent → {to_addr}")
    except Exception as e:
        logger.error(f"Email send failed: {e}")
