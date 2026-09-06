from __future__ import annotations

from typing import TYPE_CHECKING

import boto3
import pytest
from allauth.mfa.totp.internal import auth as totp_auth
from django.conf import settings as django_settings
from moto import mock_aws

from sandbox.organisations.tests.factories import MembershipFactory
from sandbox.organisations.tests.factories import OrganisationFactory
from sandbox.integrations.fakes import reset_fakes
from sandbox.users.tests.factories import UserFactory

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.test import Client

    from sandbox.organisations.models import Membership
    from sandbox.organisations.models import Organisation
    from sandbox.users.models import User


@pytest.fixture(autouse=True)
def media_storage(settings, tmpdir) -> None:
    """Keep anything uploaded during a test inside that test's tmpdir."""
    settings.MEDIA_ROOT = tmpdir.strpath


@pytest.fixture(autouse=True)
def _reset_integration_fakes() -> None:
    """Fake state is cache-backed, so it would otherwise leak between tests."""
    reset_fakes()


@pytest.fixture
def user(db) -> User:
    return UserFactory.create()


@pytest.fixture
def organisation(db) -> Organisation:
    """A vendor company that signed up but has not finished onboarding."""
    return OrganisationFactory.create(name="Sunrise Health Systems")


@pytest.fixture
def onboarded_organisation(db) -> Organisation:
    return OrganisationFactory.create(name="Sunrise Health Systems", onboarded=True)


@pytest.fixture
def owner_membership(onboarded_organisation: Organisation) -> Membership:
    """The owner of an onboarded organisation — the common signed-in actor."""
    return MembershipFactory.create(
        organisation=onboarded_organisation,
        role="owner",
        user__name="Meera Krishnan",
        user__email="meera@sunrise.in",
    )


@pytest.fixture
def sign_in(client: Client) -> Callable[[User], Client]:
    """Sign a user into the shared test client and hand the client back."""

    def _sign_in(signed_in_user: User) -> Client:
        client.force_login(signed_in_user)
        return client

    return _sign_in


@pytest.fixture
def mock_s3():
    """A real S3 conversation against `moto`, for anything that stores a file."""
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(
            Bucket=django_settings.AWS_STORAGE_BUCKET_NAME,
        )
        yield


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
