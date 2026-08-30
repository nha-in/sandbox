"""Delivery. Runs in a worker, never in a request thread.

Retry policy lives here rather than in `IntegrationClient` on purpose: the send
is a POST, and a transport-level retry of a POST is a second email. The HTTP
layer therefore gives up after one attempt and this task decides — with the row
as its memory — whether to try again.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from celery import shared_task
from django.conf import settings

from sandbox.integrations.ports import AdapterError
from sandbox.integrations.ports import NotificationChannel
from sandbox.integrations.ports import NotificationMessage
from sandbox.integrations.registry import get_notification_gateway
from sandbox.notifications.models import Message
from sandbox.notifications.models import MessageState

if TYPE_CHECKING:
    from celery import Task

logger = logging.getLogger(__name__)

REJECTED = "REJECTED"


def _backoff(attempts: int) -> float:
    """Exponential from the settings base, capped so nothing waits unboundedly."""
    delay = settings.NOTIFICATION_RETRY_BACKOFF_SECONDS * (2 ** (attempts - 1))
    return min(delay, settings.NOTIFICATION_RETRY_BACKOFF_MAX_SECONDS)


def _fail(
    task: Task,
    message: Message,
    code: str,
    detail: str,
    *,
    retryable: bool,
) -> None:
    """Retry if there is any point, otherwise settle the row as FAILED."""
    if retryable and message.attempts < settings.NOTIFICATION_MAX_ATTEMPTS:
        message.note_error(code, detail)
        raise task.retry(countdown=_backoff(message.attempts))

    message.mark_failed(code, detail)
    # ERROR reaches Sentry through the logging integration (production.py).
    logger.error(
        "notification %s to %s gave up after %s attempts: %s",
        message.external_id,
        message.template_key,
        message.attempts,
        message.last_error,
    )


# max_retries=None so `attempts` on the row is the single source of truth;
# otherwise Celery's own default of 3 would silently cap the settings value.
@shared_task(bind=True, max_retries=None)
def send_notification(task: Task, message_id: int) -> None:
    """Deliver one logged message. Safe to re-run: only PENDING rows are sent."""
    message = Message.objects.filter(pk=message_id).first()
    if message is None:
        logger.warning("notification %s disappeared before delivery", message_id)
        return

    # A duplicate delivery is worse than a missing one — an "approved" mail sent
    # twice reads as two approvals.
    if message.state != MessageState.PENDING:
        return

    message.attempts += 1
    message.save(update_fields=["attempts", "modified_date"])

    try:
        result = get_notification_gateway().send(
            NotificationMessage(
                template=message.template_key,
                to=message.recipient,
                context=message.params,
                channel=NotificationChannel(message.channel),
            ),
        )
    except AdapterError as error:
        _fail(task, message, error.code, error.message, retryable=error.retryable)
        return

    if not result.accepted:
        _fail(task, message, REJECTED, "gateway declined the message", retryable=True)
        return

    message.mark_sent(result.provider_message_id or "")
