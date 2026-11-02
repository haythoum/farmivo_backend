"""Push notification senders."""

from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger(__name__)


REMINDERS_CHANNEL = "farmivo_reminders"
MEMBERS_CHANNEL = "farmivo_members"
BRAND_COLOR = "#1F6F6B"
ANDROID_ICON = "ic_notification"  # small monochrome Farmivo icon in the Android app (res/drawable)


class Notifier(Protocol):
    """Interface of a push sender."""
    def send(self, tokens: list[str], title: str, body: str, data: dict[str, str],
             channel: str = REMINDERS_CHANNEL) -> list[str]:
        """Send a push notification (shown by the phone, plus ``data`` for the app). Returns tokens that are
        no longer valid. ``channel`` is the Android notification channel."""
        ...


class NullNotifier:
    """Records messages instead of sending them (tests / local development)."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send(self, tokens: list[str], title: str, body: str, data: dict[str, str],
             channel: str = REMINDERS_CHANNEL) -> list[str]:
        if tokens:
            self.sent.append({"tokens": list(tokens), "title": title, "body": body, "data": data,
                              "channel": channel})
        return []


def fcm_message(tokens: list[str], title: str, body: str, data: dict[str, str], channel: str):
    """The FCM multicast message: a visible notification (Farmivo icon and colour on Android, sound on iOS)
    plus ``data`` (all values strings) that the app reads when the notification is tapped."""
    from firebase_admin import messaging

    return messaging.MulticastMessage(
        tokens=tokens,
        notification=messaging.Notification(title=title, body=body),
        data={k: str(v) for k, v in data.items() if v is not None},
        android=messaging.AndroidConfig(
            priority="high",
            notification=messaging.AndroidNotification(channel_id=channel, icon=ANDROID_ICON, color=BRAND_COLOR),
        ),
        apns=messaging.APNSConfig(
            headers={"apns-priority": "10"},
            payload=messaging.APNSPayload(aps=messaging.Aps(sound="default", mutable_content=True)),
        ),
    )


class FcmNotifier:
    """Sends pushes with Firebase Cloud Messaging in batches of 500; returns tokens FCM reports as invalid."""
    def send(self, tokens: list[str], title: str, body: str, data: dict[str, str],
             channel: str = REMINDERS_CHANNEL) -> list[str]:
        if not tokens:
            return []
        from firebase_admin import messaging

        invalid: list[str] = []
        for start in range(0, len(tokens), 500):  # FCM multicast limit
            batch = tokens[start : start + 500]
            message = fcm_message(batch, title, body, data, channel)
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
