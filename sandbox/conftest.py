from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from allauth.mfa.totp.internal import auth as totp_auth

from sandbox.integrations.fakes import reset_fakes
from sandbox.users.tests.factories import UserFactory

if TYPE_CHECKING:
    from sandbox.users.models import User


@pytest.fixture(autouse=True)
def _media_storage(settings, tmpdir) -> None:
    settings.MEDIA_ROOT = tmpdir.strpath


@pytest.fixture(autouse=True)
def _reset_integration_fakes() -> None:
    """Fake state is cache-backed, so it would otherwise leak between tests."""
    reset_fakes()


@pytest.fixture
def user(db) -> User:
    return UserFactory.create()


@pytest.fixture
def enable_mfa():
    """Give a user a TOTP authenticator, as VerificationRequiredMiddleware demands."""

    def _enable(user: User) -> User:
        totp_auth.TOTP.activate(user, totp_auth.generate_totp_secret())
        return user

    return _enable


@pytest.fixture
def admin_client(admin_client, admin_user, enable_mfa):
    enable_mfa(admin_user)
    return admin_client
