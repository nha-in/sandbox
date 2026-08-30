from __future__ import annotations

import pytest
from celery.exceptions import Retry

from sandbox.integrations.fakes import always_fail
from sandbox.integrations.fakes import recorded_sends
from sandbox.integrations.ports import ExternalSystem
from sandbox.notifications.models import Channel
from sandbox.notifications.models import Message
from sandbox.notifications.models import MessageState
from sandbox.notifications.models import TemplateKey
from sandbox.notifications.tasks import send_notification

pytestmark = pytest.mark.django_db

MAX_ATTEMPTS = 3


def _pending(**overrides) -> Message:
    fields = {
        "recipient": "dev@example.test",
        "template_key": TemplateKey.PRODUCTION_APPROVED,
        "params": {"reference": "SBX-2026-00001"},
    } | overrides
    return Message.objects.create(**fields)


def test_a_successful_send_settles_the_row() -> None:
    message = _pending()

    send_notification.delay(message.pk)

    message.refresh_from_db()
    assert message.state == MessageState.SENT
    assert message.attempts == 1
    assert message.provider_message_id
    assert len(recorded_sends()) == 1


def test_the_row_is_the_idempotency_key() -> None:
    """Re-running a settled row must not send a second copy."""
    message = _pending(state=MessageState.SENT)

    send_notification.delay(message.pk)

    assert recorded_sends() == []
    message.refresh_from_db()
    assert message.attempts == 0


def test_a_missing_row_is_not_an_error() -> None:
    send_notification.delay(999_999)

    assert recorded_sends() == []


def test_a_retryable_failure_retries_and_keeps_the_row_pending() -> None:
    always_fail(ExternalSystem.NOTIFICATION, code="UPSTREAM_DOWN", retryable=True)
    message = _pending()

    with pytest.raises(Retry):
        send_notification.delay(message.pk)

    message.refresh_from_db()
    assert message.state == MessageState.PENDING
    assert message.attempts == 1
    assert "UPSTREAM_DOWN" in message.last_error


def test_a_non_retryable_failure_fails_immediately() -> None:
    always_fail(ExternalSystem.NOTIFICATION, code="BAD_ADDRESS", retryable=False)
    message = _pending()

    send_notification.delay(message.pk)

    message.refresh_from_db()
    assert message.state == MessageState.FAILED
    assert message.attempts == 1
    assert "BAD_ADDRESS" in message.last_error


def test_the_last_allowed_attempt_settles_as_failed(settings) -> None:
    """Terminal failure is bounded by `attempts`, not by Celery's own counter."""
    settings.NOTIFICATION_MAX_ATTEMPTS = MAX_ATTEMPTS
    always_fail(ExternalSystem.NOTIFICATION, code="UPSTREAM_DOWN", retryable=True)
    message = _pending(attempts=MAX_ATTEMPTS - 1)

    send_notification.delay(message.pk)

    message.refresh_from_db()
    assert message.state == MessageState.FAILED
    assert message.attempts == MAX_ATTEMPTS


def test_backoff_grows_and_is_capped(settings) -> None:
    from sandbox.notifications.tasks import _backoff  # noqa: PLC0415

    settings.NOTIFICATION_RETRY_BACKOFF_SECONDS = 10
    settings.NOTIFICATION_RETRY_BACKOFF_MAX_SECONDS = 30

    assert [_backoff(n) for n in (1, 2, 3, 4)] == [10, 20, 30, 30]


def test_an_sms_row_reaches_the_gateway_as_sms() -> None:
    message = _pending(channel=Channel.SMS, recipient="9999999999")

    send_notification.delay(message.pk)

    assert recorded_sends()[0]["channel"] == "SMS"
