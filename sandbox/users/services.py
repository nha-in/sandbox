"""Contact verification — the only writer of the `*_verified_at` stamps.

Code generation, expiry and attempt counting live in `sandbox.otp`; this module
owns the issue-rate limit (as the legacy controller did) and the decision to
trust a verified contact.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from allauth.account.models import EmailAddress
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from sandbox.integrations.ports import NotificationChannel
from sandbox.otp import send_otp as issue_code
from sandbox.otp import verify_otp as check_code
from sandbox.otp.service import EXPIRED
from sandbox.utils.errors import OTP_EXPIRED
from sandbox.utils.errors import OTP_INVALID
from sandbox.utils.errors import OTP_RATE_LIMITED
from sandbox.utils.errors import DomainError

if TYPE_CHECKING:
    from sandbox.users.models import User

_RATE_KEY = "otp_issue:{identity}"
_COOLDOWN_KEY = "otp_cooldown:{identity}"


def seconds_until_resend(identity: str) -> int:
    """What C4's resend button counts down from; 0 once a resend is allowed."""
    resume_at = cache.get(_COOLDOWN_KEY.format(identity=identity))
    if resume_at is None:
        return 0
    return max(0, int(resume_at - time.time()))


def _check_cooldown(identity: str) -> None:
    remaining = seconds_until_resend(identity)
    if remaining:
        message = f"Please wait {remaining}s before requesting another code."
        raise DomainError(message, code=OTP_RATE_LIMITED)


def _start_cooldown(identity: str) -> None:
    cooldown = settings.OTP_RESEND_COOLDOWN_SECONDS
    cache.set(
        _COOLDOWN_KEY.format(identity=identity),
        time.time() + cooldown,
        cooldown,
    )


def _check_issue_rate(identity: str) -> None:
    """Fixed window, mirroring legacy: INCR, and set the TTL on the first hit."""
    key = _RATE_KEY.format(identity=identity)
    if cache.add(key, 1, settings.OTP_ISSUE_WINDOW_SECONDS):
        return
    try:
        issued = cache.incr(key)
    except ValueError:  # expired between add() and incr()
        cache.set(key, 1, settings.OTP_ISSUE_WINDOW_SECONDS)
        return
    if issued > settings.OTP_ISSUE_MAX:
        message = "Too many OTP requests. Please try again shortly."
        raise DomainError(message, code=OTP_RATE_LIMITED)


def request_otp(*, identity: str, channel: NotificationChannel) -> str:
    """Returns the transaction id the wizard holds until the code is entered.

    Takes the contact rather than the user: the wizard verifies a phone before
    it is trusted enough to persist, so it may not be on the account yet.
    """
    _check_cooldown(identity)
    _check_issue_rate(identity)
    challenge = issue_code(identity, channel=channel).transaction_id
    _start_cooldown(identity)
    return challenge


def verify_otp(
    *,
    user: User,
    identity: str,
    channel: NotificationChannel,
    challenge: str,
    code: str,
) -> None:
    result = check_code(challenge, identity, code)
    if not result.verified:
        expired = result.reason == EXPIRED
        message = (
            "That code has expired. Request a new one."
            if expired
            else "That code is not correct."
        )
        raise DomainError(message, code=OTP_EXPIRED if expired else OTP_INVALID)

    if channel is NotificationChannel.EMAIL:
        if identity != user.email:
            message = "That email does not belong to this account."
            raise DomainError(message)
        user.email_verified_at = timezone.now()
        fields = ["email_verified_at"]
        # allauth no longer sends its own confirmation link, so keep its record
        # in step rather than leaving a permanently unverified EmailAddress
        EmailAddress.objects.filter(user=user, email=identity).update(verified=True)
    else:
        # a verified number is trustworthy enough to store
        user.phone = identity
        user.phone_verified_at = timezone.now()
        fields = ["phone", "phone_verified_at"]

    user.save(update_fields=fields)
