"""Contact-verification codes.

Deliberately standalone: it knows nothing about users, organisations or
applications, and works on an opaque `identity` string. Codes are generated,
stored and checked here; delivery goes out through the notification port, so
the code never reaches the caller.
"""

from __future__ import annotations

from sandbox.otp.service import OtpChallenge
from sandbox.otp.service import OtpVerification
from sandbox.otp.service import send_otp
from sandbox.otp.service import verify_otp

__all__ = ["OtpChallenge", "OtpVerification", "send_otp", "verify_otp"]
