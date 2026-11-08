import logging
import smtplib
from email.message import EmailMessage

from common.config import get_settings

log = logging.getLogger("tenant_core.email")


def send_reset_email(to: str, token: str) -> None:
    """Never raises: a mail failure must not change the API response (that would leak which emails exist)."""
    s = get_settings()
    link = f"{s.frontend_url.rstrip('/')}/reset-password?token={token}"

    if not s.mail_server:
        if s.app_env == "development":
            log.warning("MAIL_SERVER not set. Reset link for %s: %s", to, link)
        else:
            log.error("MAIL_SERVER not set; cannot send reset email")
        return

    msg = EmailMessage()
    msg["Subject"] = "Password reset request"
    msg["From"] = s.mail_from
    msg["To"] = to
    msg.set_content(
        f"You asked to reset your password.\n\nOpen this link to choose a new one:\n{link}\n\n"
        f"The link works once and expires in {s.reset_token_minutes} minutes.\n"
        "If you did not ask for this, ignore this email."
    )
    msg.add_alternative(
        f"<p>You asked to reset your password.</p>"
        f'<p><a href="{link}">Choose a new password</a></p>'
        f"<p>The link works once and expires in {s.reset_token_minutes} minutes. "
        "If you did not ask for this, ignore this email.</p>",
        subtype="html",
    )
    try:
        with smtplib.SMTP(s.mail_server, s.mail_port, timeout=10) as server:
            server.starttls()
            if s.mail_username:
                server.login(s.mail_username, s.mail_password or "")
            server.send_message(msg)
    except Exception:
        log.exception("Failed to send reset email")
