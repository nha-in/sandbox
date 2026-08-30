from __future__ import annotations

import hmac
import secrets
import time
import uuid
from dataclasses import dataclass
from hashlib import sha256

from django.conf import settings
from django.core.cache import cache

from sandbox.integrations.ports import NotificationChannel
from sandbox.notifications.services import send_now

_CHALLENGE_KEY = "otp:challenge:{transaction_id}"
_IDENTITY_KEY = "otp:identity:{identity}"
#: cache entries outlive `expires_at` so a late attempt is reported as expired
#: rather than silently looking like an unknown challenge
_CACHE_SLACK_SECONDS = 60

EXPIRED = "EXPIRED"
INVALID = "INVALID"


@dataclass(frozen=True, slots=True)
class OtpChallenge:
    """Legacy carried this id as `emailTransactioId` on the enrollment."""

    transaction_id: str


@dataclass(frozen=True, slots=True)
class OtpVerification:
    verified: bool
    reason: str = ""


def _digest(code: str) -> str:
    """Keyed so a stolen cache cannot be brute-forced offline; the 6-digit space
    is small, so the attempt cap and TTL are what really protect it."""
    return hmac.new(
        settings.SECRET_KEY.encode(),
        code.encode(),
        sha256,
    ).hexdigest()


def send_otp(
    identity: str,
    channel: NotificationChannel = NotificationChannel.EMAIL,
) -> OtpChallenge:
    """Issue a code and send it. Any earlier code for `identity` stops working."""
    previous = cache.get(_IDENTITY_KEY.format(identity=identity))
    if previous:
        cache.delete(_CHALLENGE_KEY.format(transaction_id=previous))

    transaction_id = uuid.uuid4().hex
    code = f"{secrets.randbelow(1_000_000):06d}"
    ttl = settings.OTP_TTL_SECONDS
    cache.set(
        _CHALLENGE_KEY.format(transaction_id=transaction_id),
        {
            "identity": identity,
            "digest": _digest(code),
            "attempts": 0,
            "expires_at": time.time() + ttl,
        },
        ttl + _CACHE_SLACK_SECONDS,
    )
    cache.set(
        _IDENTITY_KEY.format(identity=identity),
        transaction_id,
        ttl + _CACHE_SLACK_SECONDS,
    )

    # `send_now`, not `enqueue`: the delivery log records that a code went to
    # this address and whether it landed, but never the code. Legacy logged the
    # rendered body, so `notification_audit` still holds every OTP it ever sent.
    send_now(
        template_key="send-otp",
        recipient=identity,
        context={"code": code},
        channel=channel,
    )
    return OtpChallenge(transaction_id=transaction_id)


def verify_otp(challenge: str, identity: str, code: str) -> OtpVerification:
    key = _CHALLENGE_KEY.format(transaction_id=challenge)
    record = cache.get(key)

    if record is None or record["identity"] != identity:
        return OtpVerification(verified=False, reason=EXPIRED)
    if record["expires_at"] < time.time():
        cache.delete(key)
        return OtpVerification(verified=False, reason=EXPIRED)
    if record["attempts"] >= settings.OTP_MAX_ATTEMPTS:
        cache.delete(key)
        return OtpVerification(verified=False, reason=EXPIRED)

    if hmac.compare_digest(record["digest"], _digest(code)):
        cache.delete(key)  # single use
        return OtpVerification(verified=True)

    record["attempts"] += 1
    remaining = record["expires_at"] - time.time()
    cache.set(key, record, remaining + _CACHE_SLACK_SECONDS)
    return OtpVerification(verified=False, reason=INVALID)
