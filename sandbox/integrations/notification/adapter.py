"""ABDM's notification gateway — the thing that actually puts mail on the wire.

Grounded in `NotificationFClient` and `NotificationServiceImpl`: the endpoint is
`POST /internal/v3/notification/message` with `REQUEST-ID` / `TIMESTAMP` headers
and a body of `origin`, `type`, `contentType`, `sender`, and two key/value lists
(`receiver`, `notification`). We keep that shape.

What we drop is the second service. Legacy fetched every template **body** at
send time from a separate notification-DB (`GET /internal/v3/notification/
template/id/{id}`) and string-substituted `var1` into it, so an unreachable
notification-DB meant no mail at all, and a body edited in another service
silently changed ours. Bodies are Django templates in this repo; the gateway
template id still travels, for the provider's own routing and audit.
"""

from __future__ import annotations

import uuid
from datetime import UTC
from datetime import datetime
from typing import TYPE_CHECKING
from typing import Any

from django.conf import settings
from django.template.loader import render_to_string

from sandbox.integrations.http import HttpPolicy
from sandbox.integrations.http import IntegrationClient
from sandbox.integrations.ports import AdapterError
from sandbox.integrations.ports import ExternalSystem
from sandbox.integrations.ports import NotificationChannel
from sandbox.integrations.ports import SendResult

if TYPE_CHECKING:
    import httpx

    from sandbox.integrations.ports import NotificationMessage

REQUEST_ID_HEADER = "REQUEST-ID"
TIMESTAMP_HEADER = "TIMESTAMP"

#: `NotificationContentType` — otp mail is rate-shaped differently by the provider.
CONTENT_TYPE_OTP = "otp"
CONTENT_TYPE_INFO = "info"
OTP_TEMPLATE_KEY = "send-otp"

#: `NotificationEnum` / `NotificationType`
_CHANNEL_TYPE = {
    NotificationChannel.EMAIL: "email",
    NotificationChannel.SMS: "sms",
}
_CHANNEL_RECEIVER_KEY = {
    NotificationChannel.EMAIL: "email",
    NotificationChannel.SMS: "mobile",
}

#: statuses the gateway reports for a message it took responsibility for
ACCEPTED_STATUSES = frozenset({"SENT", "SUCCESS", "ACCEPTED"})


class AbdmNotificationGateway:
    """Implements `NotificationGateway` against the ABDM notification service."""

    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        policy = HttpPolicy(
            system=ExternalSystem.NOTIFICATION,
            base_url=settings.NOTIFICATION_BASE_URL.rstrip("/"),
            read_timeout=settings.NOTIFICATION_READ_TIMEOUT_SECONDS,
        )
        self._client = IntegrationClient(policy, transport=transport)

    def send(self, message: NotificationMessage) -> SendResult:
        template_id = self._template_id(message.template)
        channel = message.channel

        response = self._client.request(
            "POST",
            settings.NOTIFICATION_MESSAGE_PATH,
            op="send",
            # Never retried at this level: a resent POST is a second email. The
            # Celery task retries, because it can see whether the row settled.
            idempotent=False,
            headers=self._gateway_headers(),
            json={
                "origin": settings.NOTIFICATION_ORIGIN,
                "type": [_CHANNEL_TYPE[channel]],
                "contentType": self._content_type(message.template),
                "sender": settings.NOTIFICATION_SENDER,
                "receiver": [
                    {"key": _CHANNEL_RECEIVER_KEY[channel], "value": message.to},
                ],
                "notification": [
                    {"key": "templateId", "value": template_id},
                    {"key": "subject", "value": self._subject(message.template)},
                    {"key": "content", "value": self._render(message)},
                ],
            },
        )
        return self._result(response)

    # Internals

    @staticmethod
    def _template_id(template_key: str) -> str:
        template_id = settings.NOTIFICATION_TEMPLATE_IDS.get(template_key)
        if not template_id:
            raise AdapterError(
                ExternalSystem.NOTIFICATION,
                "UNKNOWN_TEMPLATE",
                retryable=False,
                message=(
                    f"{template_key} has no gateway template id; "
                    "set settings.NOTIFICATION_TEMPLATE_IDS"
                ),
            )
        return str(template_id)

    @staticmethod
    def _subject(template_key: str) -> str:
        return settings.NOTIFICATION_SUBJECTS.get(template_key, "ABDM Sandbox")

    @staticmethod
    def _content_type(template_key: str) -> str:
        if template_key == OTP_TEMPLATE_KEY:
            return CONTENT_TYPE_OTP
        return CONTENT_TYPE_INFO

    @staticmethod
    def _render(message: NotificationMessage) -> str:
        # Autoescaping stays on despite the .txt bodies: a reviewer's comment is
        # user input, and the provider may deliver this content as HTML.
        return render_to_string(
            f"notifications/{message.template}.txt",
            dict(message.context),
        ).strip()

    @staticmethod
    def _gateway_headers() -> dict[str, str]:
        return {
            REQUEST_ID_HEADER: str(uuid.uuid4()),
            # GeneralUtils.timeStampWithT — UTC, milliseconds, trailing Z.
            TIMESTAMP_HEADER: datetime.now(UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
        }

    def _result(self, response: httpx.Response) -> SendResult:
        payload = self._json(response)
        status = str(payload.get("status", "")).upper()
        # No status at all means the gateway answered 2xx and said nothing;
        # `NotificationResponseDTO` carries only `status`, so treat that as
        # accepted rather than inventing a failure the provider did not report.
        accepted = not status or status in ACCEPTED_STATUSES
        return SendResult(
            accepted=accepted,
            provider_message_id=payload.get("messageId") or None,
        )

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        if not response.content:
            return {}
        try:
            payload = response.json()
        except ValueError as exc:
            raise AdapterError(
                ExternalSystem.NOTIFICATION,
                "MALFORMED_RESPONSE",
                retryable=False,
                message="send did not return JSON",
            ) from exc
        if not isinstance(payload, dict):
            raise AdapterError(
                ExternalSystem.NOTIFICATION,
                "MALFORMED_RESPONSE",
                retryable=False,
                message="send returned a non-object body",
            )
        return payload
