"""Sending email: the 6-digit verification code after sign-up, through Mailjet (Send API v3.1).

Configured with MAILJET_API_KEY / MAILJET_API_SECRET (see .env.example). Without the key the code is
written to the server log instead (WARNING level), so sign-up can be tested before Mailjet is set up.
"""
from __future__ import annotations

import logging
from typing import Protocol

from app.i18n import t

log = logging.getLogger("farmivo.mailer")


class MailError(Exception):
    """The email could not be sent (bad API key, unvalidated sender, network error, Mailjet refusal)."""


class Mailer(Protocol):
    """Anything that can deliver a verification code (Mailjet in production, a fake in the tests)."""

    def send_code(self, to: str, code: str, minutes: int, lang: str = "en") -> None: ...


def code_text(code: str, minutes: int, lang: str = "en") -> str:
    """Plain-text body of the verification email in ``lang``."""
    return (
        f"{t('email.welcome', lang)}\n\n"
        f"{t('email.code_is', lang, code=code)}\n\n"
        f"{t('email.enter', lang)} {t('email.expires', lang, minutes=minutes)}\n\n"
        f"{t('email.ignore', lang)}\n\n"
        f"Farmivo - {t('email.slogan', lang)} - Powered by Quadralens\n"
    )


def code_html(code: str, minutes: int, lang: str = "en") -> str:
    """Branded HTML body of the verification email (teal header, big code); right-to-left for Arabic."""
    direction = "rtl" if lang == "ar" else "ltr"
    align = "right" if lang == "ar" else "left"
    spaced = " ".join(code)
    return f"""\
<!doctype html>
<html lang="{lang}" dir="{direction}"><body dir="{direction}" style="margin:0;padding:0;background:#FBF6EE;font-family:Arial,Helvetica,sans-serif;color:#1E2A29">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#FBF6EE;padding:24px 0">
<tr><td align="center">
<table role="presentation" dir="{direction}" width="480" cellpadding="0" cellspacing="0" style="max-width:480px;width:100%;background:#ffffff;border-radius:16px;overflow:hidden;border:1px solid #DCE5E3;text-align:{align}">
<tr><td style="background:#1F6F6B;padding:22px 28px;color:#ffffff">
<div style="font-size:26px;font-weight:bold">Farmivo</div>
<div style="font-size:14px;color:#F7EBDD;margin-top:4px">{t('email.slogan', lang)}</div>
</td></tr>
<tr><td style="padding:28px">
<div style="font-size:18px;font-weight:bold">{t('email.your_code', lang)}</div>
<div style="font-size:15px;color:#5B6B69;margin-top:8px">{t('email.enter', lang)}</div>
<div dir="ltr" style="font-size:36px;font-weight:bold;letter-spacing:10px;color:#134A47;background:#DDEEEC;border-radius:12px;padding:16px 0;text-align:center;margin:22px 0">{spaced}</div>
<div style="font-size:14px;color:#5B6B69">{t('email.expires', lang, minutes=minutes)}</div>
<div style="font-size:13px;color:#5B6B69;margin-top:18px">{t('email.ignore', lang)}</div>
</td></tr>
<tr><td style="padding:16px 28px;border-top:1px solid #E8EFED;font-size:12px;color:#5B6B69;text-align:center">
{t('email.slogan', lang)} &middot; Powered by Quadralens
</td></tr>
</table>
</td></tr></table>
</body></html>
"""


def code_message(sender_email: str, sender_name: str, to: str, code: str, minutes: int, lang: str = "en") -> dict:
    """The Mailjet Send API v3.1 payload for one verification email in ``lang``."""
    return {
        "Messages": [
            {
                "From": {"Email": sender_email, "Name": sender_name},
                "To": [{"Email": to}],
                "Subject": t("email.subject", lang),
                "TextPart": code_text(code, minutes, lang),
                "HTMLPart": code_html(code, minutes, lang),
                "CustomID": "farmivo-verification",
            }
        ]
    }


class MailjetMailer:
    """Sends through Mailjet's Send API v3.1 (package ``mailjet_rest``)."""

    def __init__(self, api_key: str, api_secret: str, sender_email: str, sender_name: str = "Farmivo",
                 timeout: float = 10) -> None:
        self.api_key, self.api_secret = api_key, api_secret
        self.sender_email, self.sender_name, self.timeout = sender_email, sender_name, timeout

    def _client(self, version: str = "v3.1"):
        from mailjet_rest import Client

        return Client(auth=(self.api_key, self.api_secret), version=version)

    def send_code(self, to: str, code: str, minutes: int, lang: str = "en") -> None:
        """Send the verification email in ``lang``. Raises MailError unless Mailjet reports success."""
        data = code_message(self.sender_email, self.sender_name, to, code, minutes, lang)
        try:
            result = self._client().send.create(data=data, timeout=self.timeout)
            body = result.json()
        except Exception as exc:  # noqa: BLE001 - network errors, invalid JSON
            raise MailError(f"Mailjet request failed: {exc}") from exc
        status = (body.get("Messages") or [{}])[0].get("Status") if isinstance(body, dict) else None
        if result.status_code != 200 or status != "success":
            raise MailError(f"Mailjet refused the email to {to}: HTTP {result.status_code} {body}")

    def check(self) -> list[str]:
        """Validate the API key and return the active sender addresses (used by scripts/check_setup.py)."""
        try:
            result = self._client("v3").sender.get(filters={"Limit": 100}, timeout=self.timeout)
            body = result.json()
        except Exception as exc:  # noqa: BLE001
            raise MailError(f"Mailjet request failed: {exc}") from exc
        if result.status_code != 200:
            raise MailError(f"Mailjet answered HTTP {result.status_code}: {body}")
        return [s.get("Email", "") for s in body.get("Data", []) if s.get("Status") == "Active"]


class LogMailer:
    """Used when MAILJET_API_KEY is empty: writes the code to the server log instead of sending it."""

    def send_code(self, to: str, code: str, minutes: int, lang: str = "en") -> None:
        """Log the code at WARNING level (look for 'verification code for' in the log)."""
        try:
            from flask import current_app

            logger = current_app.logger  # same log as the rest of the API (supervisor's err log)
        except RuntimeError:  # outside a request, e.g. a script
            logger = log
        logger.warning("Email not configured; verification code for %s: %s", to, code)
