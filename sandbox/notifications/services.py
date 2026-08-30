"""Writing a message down and scheduling it. The only way to send anything.

Nothing calls the gateway from here: `enqueue()` writes a PENDING row and hands
the delivery to Celery on commit. That ordering is the point — a workflow
transition that rolls back must not have emailed anyone that it happened.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from django.db import transaction

from sandbox.integrations.ports import AdapterError
from sandbox.integrations.ports import NotificationChannel
from sandbox.integrations.ports import NotificationMessage
from sandbox.integrations.registry import get_notification_gateway
from sandbox.notifications.models import Channel
from sandbox.notifications.models import Message
from sandbox.notifications.models import TemplateKey
from sandbox.notifications.tasks import send_notification
from sandbox.utils.errors import DomainError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sandbox.applications.models import Application
    from sandbox.users.models import User

#: Substrings that make a params key refuse to be logged. Deliberately excludes
#: "code": an OTP is a param, and `send-otp` is dispatched without a log row
#: (see the note in `otp.service`) rather than by pretending the code is safe.
SECRET_KEY_FRAGMENTS = (
    "secret",
    "password",
    "passphrase",
    "token",
    "credential",
    "api_key",
    "apikey",
    "private_key",
)


def _offending_keys(value: object) -> list[str]:
    """Every secret-ish key anywhere in `value`, nesting included."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            name = str(key)
            if any(fragment in name.lower() for fragment in SECRET_KEY_FRAGMENTS):
                found.append(name)
            found.extend(_offending_keys(item))
    elif isinstance(value, list | tuple):
        for item in value:
            found.extend(_offending_keys(item))
    return found


def _validate(template_key: str, recipient: str) -> None:
    if template_key not in TemplateKey.values:
        message = f"{template_key!r} is not a v0 notification template"
        raise DomainError(message, code="unknown_template")

    if not recipient:
        message = f"{template_key} has no recipient to send to"
        raise DomainError(message, code="no_recipient")


def enqueue(  # noqa: PLR0913 - all keyword-only; collapsing them would hide the row's shape
    *,
    template_key: str,
    recipient: str,
    params: Mapping[str, Any] | None = None,
    application: Application | None = None,
    user: User | None = None,
    channel: str = Channel.EMAIL,
) -> Message:
    """Log a message as PENDING and schedule its send for after the commit.

    Raises `DomainError` for an unknown template, an empty recipient, or params
    carrying anything that looks like a secret.
    """
    _validate(template_key, recipient)

    params = dict(params or {})
    offenders = _offending_keys(params)
    if offenders:
        keys = ", ".join(sorted(set(offenders)))
        message = f"notification params may not carry secrets: {keys}"
        raise DomainError(message, code="secret_in_params")

    record = Message.objects.create(
        application=application,
        user=user,
        recipient=recipient,
        channel=channel,
        template_key=template_key,
        params=params,
    )
    transaction.on_commit(lambda: send_notification.delay(record.pk))
    return record


def send_now(
    *,
    template_key: str,
    recipient: str,
    context: Mapping[str, Any],
    channel: str = Channel.EMAIL,
    user: User | None = None,
) -> Message:
    """Send in this thread, log the outcome, and never log `context`.

    For OTP, and only OTP. The context is the live code, so it reaches the
    gateway and nothing else: `params` stays empty and the row records who was
    written to, when, and whether it worked. Anything whose body is safe to keep
    goes through `enqueue` instead and gets retries with it.

    Deliberately not on-commit — the caller is a user waiting for a code, and a
    code they cannot be told failed to send is worse than a slower response.
    Re-raises the adapter's error after settling the row.
    """
    _validate(template_key, recipient)

    record = Message.objects.create(
        user=user,
        recipient=recipient,
        channel=channel,
        template_key=template_key,
        params={},
        attempts=1,
    )

    try:
        result = get_notification_gateway().send(
            NotificationMessage(
                template=template_key,
                to=recipient,
                context=context,
                channel=NotificationChannel(channel),
            ),
        )
    except AdapterError as error:
        record.mark_failed(error.code, error.message)
        raise

    if not result.accepted:
        record.mark_failed("REJECTED", "gateway declined the message")
        return record

    record.mark_sent(result.provider_message_id or "")
    return record
