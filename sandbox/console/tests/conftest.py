"""Shared console actors.

Two staff users, distinguished only by permissions: `reviewer_client` may record
an opinion and nothing else, `admin_client_` may also move the application. That
split is the point — A6 grants opinions and transitions separately, and a test
suite that only ever used a superuser could not tell whether it still did.
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Permission
from django.test import Client

from sandbox.applications.models import ApplicationState
from sandbox.applications.tests.factories import ApplicationFactory
from sandbox.organisations.tests.factories import MembershipFactory
from sandbox.organisations.tests.factories import ProductFactory
from sandbox.users.models import User
from sandbox.users.tests.factories import UserFactory
from sandbox.users.tests.factories import VerifiedUserFactory


def grant(user: User, *codenames: str) -> User:
    for codename in codenames:
        user.user_permissions.add(Permission.objects.get(codename=codename))
    return User.objects.get(pk=user.pk)


def signed_in(user) -> Client:
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def reviewer_client(enable_mfa):
    user = grant(UserFactory.create(is_staff=True), "review_application")
    return signed_in(enable_mfa(user))


@pytest.fixture
def admin_client_(enable_mfa):
    user = grant(
        UserFactory.create(is_staff=True),
        "review_application",
        "approve_application",
        "reject_application",
        "send_back_application",
    )
    return signed_in(enable_mfa(user))


@pytest.fixture
def member(db):
    """The integrator whose application the console is looking at."""
    return VerifiedUserFactory.create()


@pytest.fixture
def application(member):
    """Provisioned, because everything in the exit half starts from there."""
    product = ProductFactory.create()
    MembershipFactory.create(organisation=product.organisation, user=member)
    return ApplicationFactory.create(
        product=product,
        applicant=member,
        state=ApplicationState.PROVISIONED,
    )
