from __future__ import annotations

import time

import pytest
from django.core import mail
from django.core.cache import cache
from django.test import override_settings

from sandbox.integrations.fakes import recorded_sends
from sandbox.integrations.fakes import reset_fakes
from sandbox.integrations.ports import NotificationChannel
from sandbox.notifications.models import Message
from sandbox.notifications.models import MessageState
from sandbox.users.services import request_otp
from sandbox.users.services import seconds_until_resend
from sandbox.users.services import verify_otp
from sandbox.users.tests.factories import UserFactory
from sandbox.utils.errors import OTP_EXPIRED
from sandbox.utils.errors import OTP_INVALID
from sandbox.utils.errors import OTP_RATE_LIMITED
from sandbox.utils.errors import DomainError

pytestmark = pytest.mark.django_db

PHONE = "+919876543210"


@pytest.fixture(autouse=True)
def _clean_state():
    cache.clear()
    reset_fakes()
    yield
    cache.clear()
    reset_fakes()


def _sent_code() -> str:
    """Read from the gateway record, so it works for SMS as well as email."""
    return recorded_sends()[-1]["context"]["code"]


def test_request_otp_sends_a_six_digit_code_and_returns_a_challenge():
    user = UserFactory.create(email="applicant@example.com")

    challenge = request_otp(identity=user.email, channel=NotificationChannel.EMAIL)

    assert challenge
    code = _sent_code()
    assert code.isdigit()
    assert len(code) == 6  # noqa: PLR2004


def test_email_verification_goes_out_over_email():
    user = UserFactory.create(email="applicant@example.com")

    request_otp(identity=user.email, channel=NotificationChannel.EMAIL)

    assert recorded_sends()[-1]["channel"] == "EMAIL"
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [user.email]


def test_phone_verification_goes_out_over_sms_and_never_by_email():
    request_otp(identity=PHONE, channel=NotificationChannel.SMS)

    send = recorded_sends()[-1]
    assert send["channel"] == "SMS"
    assert send["to"] == PHONE
    assert mail.outbox == []  # a phone number must never be emailed


def test_an_otp_is_logged_as_delivered_without_recording_the_code():
    """Legacy's `notification_audit` kept the rendered body, code and all."""
    user = UserFactory.create(email="applicant@example.com")

    request_otp(identity=user.email, channel=NotificationChannel.EMAIL)

    message = Message.objects.get()
    assert message.template_key == "send-otp"
    assert message.recipient == user.email
    assert message.state == MessageState.SENT
    assert message.params == {}
    assert _sent_code() not in str(message.__dict__)


def test_verify_otp_stamps_email_verified_at():
    user = UserFactory.create(email="applicant@example.com")
    challenge = request_otp(identity=user.email, channel=NotificationChannel.EMAIL)

    verify_otp(
        user=user,
        identity=user.email,
        channel=NotificationChannel.EMAIL,
        challenge=challenge,
        code=_sent_code(),
    )

    user.refresh_from_db()
    assert user.email_verified_at is not None
    assert user.phone_verified_at is None


def test_verify_otp_stamps_phone_verified_at():
    user = UserFactory.create(phone=PHONE)
    challenge = request_otp(identity=PHONE, channel=NotificationChannel.SMS)

    verify_otp(
        user=user,
        identity=PHONE,
        channel=NotificationChannel.SMS,
        challenge=challenge,
        code=_sent_code(),
    )

    user.refresh_from_db()
    assert user.phone_verified_at is not None
    assert user.email_verified_at is None


def test_a_phone_can_be_verified_before_it_is_on_the_account():
    """The wizard verifies a number the user has just typed, so it is not yet
    stored — verification is what makes it trustworthy enough to persist."""
    user = UserFactory.create(email="applicant@example.com")
    assert user.phone == ""

    challenge = request_otp(identity=PHONE, channel=NotificationChannel.SMS)
    verify_otp(
        user=user,
        identity=PHONE,
        channel=NotificationChannel.SMS,
        challenge=challenge,
        code=_sent_code(),
    )

    user.refresh_from_db()
    assert user.phone == PHONE
    assert user.phone_verified_at is not None


def test_verify_otp_rejects_an_email_that_is_not_the_accounts():
    owner = UserFactory.create(email="owner@example.com")
    intruder = UserFactory.create(email="intruder@example.com")
    challenge = request_otp(identity=owner.email, channel=NotificationChannel.EMAIL)

    with pytest.raises(DomainError):
        verify_otp(
            user=intruder,
            identity=owner.email,
            channel=NotificationChannel.EMAIL,
            challenge=challenge,
            code=_sent_code(),
        )


def test_wrong_code_raises_otp_invalid():
    user = UserFactory.create(email="applicant@example.com")
    challenge = request_otp(identity=user.email, channel=NotificationChannel.EMAIL)

    with pytest.raises(DomainError) as exc:
        verify_otp(
            user=user,
            identity=user.email,
            channel=NotificationChannel.EMAIL,
            challenge=challenge,
            code="000000",
        )

    assert exc.value.code == OTP_INVALID
    user.refresh_from_db()
    assert user.email_verified_at is None


def test_a_code_is_single_use():
    user = UserFactory.create(email="applicant@example.com")
    challenge = request_otp(identity=user.email, channel=NotificationChannel.EMAIL)
    code = _sent_code()
    verify_otp(
        user=user,
        identity=user.email,
        channel=NotificationChannel.EMAIL,
        challenge=challenge,
        code=code,
    )

    with pytest.raises(DomainError) as exc:
        verify_otp(
            user=user,
            identity=user.email,
            channel=NotificationChannel.EMAIL,
            challenge=challenge,
            code=code,
        )

    assert exc.value.code == OTP_EXPIRED


@override_settings(OTP_RESEND_COOLDOWN_SECONDS=0)
def test_reissue_invalidates_the_previous_code():
    user = UserFactory.create(email="applicant@example.com")
    first_challenge = request_otp(
        identity=user.email,
        channel=NotificationChannel.EMAIL,
    )
    first_code = _sent_code()

    request_otp(identity=user.email, channel=NotificationChannel.EMAIL)

    with pytest.raises(DomainError) as exc:
        verify_otp(
            user=user,
            identity=user.email,
            channel=NotificationChannel.EMAIL,
            challenge=first_challenge,
            code=first_code,
        )

    assert exc.value.code == OTP_EXPIRED


@override_settings(OTP_TTL_SECONDS=-1)
def test_an_expired_code_raises_otp_expired():
    user = UserFactory.create(email="applicant@example.com")
    challenge = request_otp(identity=user.email, channel=NotificationChannel.EMAIL)

    with pytest.raises(DomainError) as exc:
        verify_otp(
            user=user,
            identity=user.email,
            channel=NotificationChannel.EMAIL,
            challenge=challenge,
            code=_sent_code(),
        )

    assert exc.value.code == OTP_EXPIRED


@override_settings(OTP_MAX_ATTEMPTS=2)
def test_the_code_is_destroyed_once_attempts_are_exhausted():
    user = UserFactory.create(email="applicant@example.com")
    challenge = request_otp(identity=user.email, channel=NotificationChannel.EMAIL)
    code = _sent_code()

    for _ in range(2):
        with pytest.raises(DomainError):
            verify_otp(
                user=user,
                identity=user.email,
                channel=NotificationChannel.EMAIL,
                challenge=challenge,
                code="000000",
            )

    with pytest.raises(DomainError) as exc:
        verify_otp(
            user=user,
            identity=user.email,
            channel=NotificationChannel.EMAIL,
            challenge=challenge,
            code=code,
        )
    assert exc.value.code == OTP_EXPIRED


@override_settings(OTP_ISSUE_MAX=3, OTP_RESEND_COOLDOWN_SECONDS=0)
def test_issue_rate_limit_is_enforced_per_identity():
    user = UserFactory.create(email="applicant@example.com")
    for _ in range(3):
        request_otp(identity=user.email, channel=NotificationChannel.EMAIL)

    with pytest.raises(DomainError) as exc:
        request_otp(identity=user.email, channel=NotificationChannel.EMAIL)

    assert exc.value.code == OTP_RATE_LIMITED


@override_settings(OTP_ISSUE_MAX=1)
def test_issue_rate_limit_does_not_leak_across_identities():
    user = UserFactory.create(email="applicant@example.com", phone=PHONE)

    request_otp(identity=user.email, channel=NotificationChannel.EMAIL)
    request_otp(identity=PHONE, channel=NotificationChannel.SMS)

    assert len(recorded_sends()) == 2  # noqa: PLR2004


@override_settings(
    OTP_ISSUE_MAX=1,
    OTP_ISSUE_WINDOW_SECONDS=1,
    OTP_RESEND_COOLDOWN_SECONDS=0,
)
def test_the_issue_window_resets():
    user = UserFactory.create(email="applicant@example.com")
    request_otp(identity=user.email, channel=NotificationChannel.EMAIL)
    with pytest.raises(DomainError):
        request_otp(identity=user.email, channel=NotificationChannel.EMAIL)

    time.sleep(1.1)

    request_otp(identity=user.email, channel=NotificationChannel.EMAIL)
    assert len(recorded_sends()) == 2  # noqa: PLR2004


def test_the_code_is_never_returned_across_the_boundary():
    user = UserFactory.create(email="applicant@example.com")

    challenge = request_otp(identity=user.email, channel=NotificationChannel.EMAIL)

    assert _sent_code() not in challenge


# --- resend cooldown (legacy RESEND_COOLDOWN_SECONDS, 90s) -------------------


def test_an_immediate_resend_is_refused():
    user = UserFactory.create(email="applicant@example.com")
    request_otp(identity=user.email, channel=NotificationChannel.EMAIL)

    with pytest.raises(DomainError) as exc:
        request_otp(identity=user.email, channel=NotificationChannel.EMAIL)

    assert exc.value.code == OTP_RATE_LIMITED
    assert len(recorded_sends()) == 1


def test_seconds_until_resend_is_zero_before_any_code_is_sent():
    assert seconds_until_resend("applicant@example.com") == 0


def test_seconds_until_resend_reports_the_remaining_cooldown():
    user = UserFactory.create(email="applicant@example.com")

    request_otp(identity=user.email, channel=NotificationChannel.EMAIL)

    remaining = seconds_until_resend(user.email)
    assert 0 < remaining <= 90  # noqa: PLR2004


@override_settings(OTP_RESEND_COOLDOWN_SECONDS=1)
def test_a_resend_is_allowed_once_the_cooldown_lapses():
    user = UserFactory.create(email="applicant@example.com")
    request_otp(identity=user.email, channel=NotificationChannel.EMAIL)

    time.sleep(1.1)

    request_otp(identity=user.email, channel=NotificationChannel.EMAIL)
    assert len(recorded_sends()) == 2  # noqa: PLR2004


def test_the_cooldown_is_per_identity():
    user = UserFactory.create(email="applicant@example.com", phone=PHONE)
    request_otp(identity=user.email, channel=NotificationChannel.EMAIL)

    request_otp(identity=PHONE, channel=NotificationChannel.SMS)

    assert len(recorded_sends()) == 2  # noqa: PLR2004
