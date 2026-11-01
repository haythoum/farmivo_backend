"""Sending email: the 6-digit verification code after sign-up.

Configured with FARMIVO_SMTP_* (see .env.example). Without FARMIVO_SMTP_HOST the code is written to the
server log instead (WARNING level), so sign-up can be tested before an email account is set up.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Protocol

log = logging.getLogger("farmivo.mailer")


class MailError(Exception):
    """The email could not be sent (connection, login or refusal by the mail server)."""


class Mailer(Protocol):
    """Anything that can deliver a verification code (SMTP in production, a fake in the tests)."""

    def send_code(self, to: str, code: str, minutes: int) -> None: ...


def code_message(sender: str, to: str, code: str, minutes: int) -> EmailMessage:
    """The verification email: a plain-text part and a branded HTML part (teal header, big code)."""
    msg = EmailMessage()
    msg["Subject"] = f"{code} is your Farmivo code"
    msg["From"] = sender
    msg["To"] = to
    msg["Message-ID"] = make_msgid(domain=sender.rpartition("@")[2].strip(">") or None)
    msg.set_content(
        f"Welcome to Farmivo!\n\n"
        f"Your verification code is: {code}\n\n"
        f"Enter it in the app to activate your account. It expires in {minutes} minutes.\n\n"
        f"If you didn't create a Farmivo account, ignore this email.\n\n"
        f"Farmivo - Smart Farming. Better Living. - Powered by Quadralens\n"
    )
    spaced = " ".join(code)
    msg.add_alternative(f"""\
<!doctype html>
<html><body style="margin:0;padding:0;background:#FBF6EE;font-family:Arial,Helvetica,sans-serif;color:#1E2A29">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#FBF6EE;padding:24px 0">
<tr><td align="center">
<table role="presentation" width="480" cellpadding="0" cellspacing="0" style="max-width:480px;width:100%;background:#ffffff;border-radius:16px;overflow:hidden;border:1px solid #DCE5E3">
<tr><td style="background:#1F6F6B;padding:22px 28px;color:#ffffff">
<div style="font-size:26px;font-weight:bold">Farmivo</div>
<div style="font-size:14px;color:#F7EBDD;margin-top:4px">Smart Farming. Better Living.</div>
</td></tr>
<tr><td style="padding:28px">
<div style="font-size:18px;font-weight:bold">Your verification code</div>
<div style="font-size:15px;color:#5B6B69;margin-top:8px">Enter this code in the Farmivo app to activate your account.</div>
<div style="font-size:36px;font-weight:bold;letter-spacing:10px;color:#134A47;background:#DDEEEC;border-radius:12px;padding:16px 0;text-align:center;margin:22px 0">{spaced}</div>
<div style="font-size:14px;color:#5B6B69">The code expires in {minutes} minutes.</div>
<div style="font-size:13px;color:#5B6B69;margin-top:18px">If you didn't create a Farmivo account, ignore this email.</div>
</td></tr>
<tr><td style="padding:16px 28px;border-top:1px solid #E8EFED;font-size:12px;color:#5B6B69;text-align:center">
Smart Farming. Better Living. &middot; Powered by Quadralens
</td></tr>
</table>
</td></tr></table>
</body></html>
""", subtype="html")
    return msg


class SmtpMailer:
    """Sends through an SMTP server. ``security`` is starttls (port 587), ssl (port 465) or none."""

    def __init__(self, host: str, port: int, user: str | None, password: str | None, sender: str,
                 security: str = "starttls", timeout: float = 10) -> None:
        self.host, self.port, self.user, self.password = host, port, user, password
        self.sender, self.security, self.timeout = sender, security.lower(), timeout

    def connect(self) -> smtplib.SMTP:
        """Open a logged-in connection (also used by scripts/check_setup.py). Raises MailError."""
        try:
            if self.security == "ssl":
                server: smtplib.SMTP = smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout,
                                                        context=ssl.create_default_context())
            else:
                server = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
                if self.security == "starttls":
                    server.starttls(context=ssl.create_default_context())
            if self.user:
                server.login(self.user, self.password or "")
            return server
        except (OSError, smtplib.SMTPException) as exc:
            raise MailError(f"SMTP {self.host}:{self.port} ({self.security}): {exc}") from exc

    def send_code(self, to: str, code: str, minutes: int) -> None:
        """Send the verification email. Raises MailError if the server refuses or cannot be reached."""
        server = self.connect()
        try:
            server.send_message(code_message(self.sender, to, code, minutes))
        except (OSError, smtplib.SMTPException) as exc:
            raise MailError(f"SMTP send to {to}: {exc}") from exc
        finally:
            try:
                server.quit()
            except (OSError, smtplib.SMTPException):
                pass


class LogMailer:
    """Used when FARMIVO_SMTP_HOST is empty: writes the code to the server log instead of sending it."""

    def send_code(self, to: str, code: str, minutes: int) -> None:
        """Log the code at WARNING level (look for 'verification code for' in the log)."""
        try:
            from flask import current_app

            logger = current_app.logger  # same log as the rest of the API (supervisor's err log)
        except RuntimeError:  # outside a request, e.g. a script
            logger = log
        logger.warning("Email not configured; verification code for %s: %s", to, code)
