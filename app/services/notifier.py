from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class Notifier(Protocol):
    def send(self, tokens: list[str], title: str, body: str, data: dict[str, str]) -> list[str]:
        """Send a push notification. Returns tokens that are no longer valid."""
        ...


class NullNotifier:
    """Records messages instead of sending them (tests / local development)."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send(self, tokens: list[str], title: str, body: str, data: dict[str, str]) -> list[str]:
        if tokens:
            self.sent.append({"tokens": list(tokens), "title": title, "body": body, "data": data})
        return []


class FcmNotifier:
    def send(self, tokens: list[str], title: str, body: str, data: dict[str, str]) -> list[str]:
        if not tokens:
            return []
        from firebase_admin import messaging

        invalid: list[str] = []
        for start in range(0, len(tokens), 500):  # FCM multicast limit
            batch = tokens[start : start + 500]
            message = messaging.MulticastMessage(
                tokens=batch,
                notification=messaging.Notification(title=title, body=body),
                data=data,
            )
            try:
                response = messaging.send_each_for_multicast(message)
            except Exception:  # noqa: BLE001 - never let push failures break the job
                logger.exception("FCM send failed")
                continue
            for token, result in zip(batch, response.responses):
                if result.success:
                    continue
                if isinstance(result.exception, (messaging.UnregisteredError, messaging.SenderIdMismatchError)):
                    invalid.append(token)
                else:
                    logger.warning("FCM error for one token: %s", result.exception)
        return invalid
