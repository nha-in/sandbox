from __future__ import annotations

from typing import TYPE_CHECKING

import boto3
import pytest
from allauth.mfa.totp.internal import auth as totp_auth
from django.conf import settings as django_settings
from django.core.files.storage import storages
from moto import mock_aws

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


def _drop_cached_declaration_storage() -> None:
    """`storages` memoizes per alias, so a cached client outlives the mock."""
    storages._storages.pop("declarations", None)  # type: ignore[attr-defined]  # noqa: SLF001


@pytest.fixture
def mock_s3():
    """A real S3 conversation against `moto`, for anything that stores a file.

    Shared rather than local to declarations because the demo seed uploads an
    exit document too.
    """
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(
            Bucket=django_settings.AWS_STORAGE_BUCKET_NAME,
        )
        _drop_cached_declaration_storage()
        yield
        _drop_cached_declaration_storage()


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
