from __future__ import annotations

import pytest
from django.db import transaction

from sandbox.applications.tests.factories import ApplicationFactory
from sandbox.integrations.fakes import always_fail
from sandbox.integrations.fakes import recorded_sends
from sandbox.integrations.ports import AdapterError
from sandbox.integrations.ports import ExternalSystem
from sandbox.notifications.models import Message
from sandbox.notifications.models import MessageState
from sandbox.notifications.models import TemplateKey
from sandbox.notifications.services import enqueue
from sandbox.notifications.services import send_now
from sandbox.utils.errors import DomainError

pytestmark = pytest.mark.django_db


def test_enqueue_writes_a_pending_row() -> None:
    message = enqueue(
        template_key=TemplateKey.PRODUCTION_APPROVED,
        recipient="dev@example.test",
        params={"reference": "SBX-2026-00001"},
    )

    assert message.state == MessageState.PENDING
    assert message.attempts == 0
    assert message.params == {"reference": "SBX-2026-00001"}


def test_enqueue_schedules_the_send_only_on_commit(
    django_capture_on_commit_callbacks,
) -> None:
    with django_capture_on_commit_callbacks() as callbacks:
        enqueue(
            template_key=TemplateKey.PRODUCTION_APPROVED,
            recipient="dev@example.test",
            params={},
        )

    assert len(callbacks) == 1


def test_a_rolled_back_transaction_leaves_no_row_and_no_send(
    django_capture_on_commit_callbacks,
) -> None:
    """A transition that rolls back must not have told anyone it happened."""

    def failing_work() -> None:
        with transaction.atomic():
            enqueue(
                template_key=TemplateKey.PRODUCTION_APPROVED,
                recipient="dev@example.test",
                params={},
            )
            message = "the surrounding work failed"
            raise RuntimeError(message)

    with (
        django_capture_on_commit_callbacks() as callbacks,
        pytest.raises(RuntimeError),
    ):
        failing_work()

    assert Message.objects.count() == 0
    assert callbacks == []


@pytest.mark.parametrize(
    "params",
    [
        {"client_secret": "s3cret"},
        {"password": "hunter2"},
        {"API_KEY": "abc"},
        {"access_token": "t"},
        {"credentials": {"private_key": "-----BEGIN"}},
        {"clients": [{"secret": "x"}]},
        # deliberate false positive: the rule is a substring match, and a name
        # that has to be argued about is a name worth changing (hooks._panel_url)
        {"credentials_url": "https://portal.test/x/"},
    ],
)
def test_enqueue_refuses_secret_shaped_params(params: dict) -> None:
    with pytest.raises(DomainError) as exc:
        enqueue(
            template_key=TemplateKey.SANDBOX_APPROVED,
            recipient="dev@example.test",
            params=params,
        )

    assert exc.value.code == "secret_in_params"
    assert Message.objects.count() == 0


def test_enqueue_allows_an_otp_code() -> None:
    """`code` is not on the deny-list — A4's template needs it."""
    message = enqueue(
        template_key=TemplateKey.SEND_OTP,
        recipient="dev@example.test",
        params={"code": "123456"},
    )

    assert message.params == {"code": "123456"}


def test_enqueue_rejects_an_unknown_template() -> None:
    with pytest.raises(DomainError) as exc:
        enqueue(template_key="not-a-template", recipient="dev@example.test")

    assert exc.value.code == "unknown_template"


def test_enqueue_rejects_an_empty_recipient() -> None:
    with pytest.raises(DomainError) as exc:
        enqueue(template_key=TemplateKey.SEND_OTP, recipient="")

    assert exc.value.code == "no_recipient"


def test_enqueue_links_the_row_to_its_application() -> None:
    application = ApplicationFactory.create()

    message = enqueue(
        template_key=TemplateKey.SANDBOX_REJECTED,
        recipient=application.applicant.email,
        params={},
        application=application,
        user=application.applicant,
    )

    assert message.application == application
    assert message.user == application.applicant


# send_now — the OTP path


def test_send_now_logs_the_send_but_not_the_context() -> None:
    """The whole point: a row saying a code went out, with no code in it."""
    message = send_now(
        template_key=TemplateKey.SEND_OTP,
        recipient="dev@example.test",
        context={"code": "123456"},
    )

    assert message.state == MessageState.SENT
    assert message.attempts == 1
    assert message.params == {}
    assert "123456" not in str(Message.objects.values_list("params", flat=True))


def test_send_now_reaches_the_gateway_with_the_code() -> None:
    send_now(
        template_key=TemplateKey.SEND_OTP,
        recipient="dev@example.test",
        context={"code": "123456"},
    )

    assert recorded_sends()[0]["context"] == {"code": "123456"}


def test_send_now_settles_the_row_and_re_raises_on_failure() -> None:
    """The caller is a waiting user, so a failure has to reach them."""
    always_fail(ExternalSystem.NOTIFICATION, code="UPSTREAM_DOWN", retryable=True)

    with pytest.raises(AdapterError):
        send_now(
            template_key=TemplateKey.SEND_OTP,
            recipient="dev@example.test",
            context={"code": "123456"},
        )

    message = Message.objects.get()
    assert message.state == MessageState.FAILED
    assert "UPSTREAM_DOWN" in message.last_error


def test_send_now_schedules_no_task(django_capture_on_commit_callbacks) -> None:
    with django_capture_on_commit_callbacks() as callbacks:
        send_now(
            template_key=TemplateKey.SEND_OTP,
            recipient="dev@example.test",
            context={"code": "123456"},
        )

    assert callbacks == []
