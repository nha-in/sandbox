"""Shared domain-error type raised by services (01-backend.md §3.3).

Views translate this into form errors/messages — one error model replaces the
legacy system's 34 bespoke exception classes.
"""

from __future__ import annotations


class DomainError(Exception):
    """Raised by a service when a use-case's business rules are violated."""

    def __init__(self, message: str, *, code: str = "invalid") -> None:
        self.code = code
        self.message = message
        super().__init__(message)


OTP_RATE_LIMITED = "OTP_RATE_LIMITED"
OTP_EXPIRED = "OTP_EXPIRED"
OTP_INVALID = "OTP_INVALID"
