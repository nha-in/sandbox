"""Actor fixtures for the route-gate matrix (C3).

Five actors, two organisations. Every URL in the portal is exercised against all
of them by `test_route_gates.py`, so these fixtures are the definition of "who
could be knocking".
"""

from __future__ import annotations

import pytest
from allauth.mfa.recovery_codes.internal import auth as recovery_codes_auth
from allauth.mfa.totp.internal import auth as totp_auth
from django.test import Client

from sandbox.organisations.tests.factories import MembershipFactory
from sandbox.organisations.tests.factories import OrganisationFactory
from sandbox.organisations.tests.factories import ProductFactory
from sandbox.users.tests.factories import VerifiedUserFactory

ANONYMOUS = "anonymous"
ORG_MEMBER = "org_member"
MEMBER_OTHER_ORG = "member_other_org"
REVIEWER = "reviewer"
STAFF = "staff"

ACTORS = (ANONYMOUS, ORG_MEMBER, MEMBER_OTHER_ORG, REVIEWER, STAFF)
STAFF_ACTORS = (REVIEWER, STAFF)


def _with_mfa(user):
    """Staff without a TOTP device are bounced by VerificationRequiredMiddleware.

    Recovery codes too, so the matrix can assert that a user who *holds* an MFA
    resource reaches its URL — otherwise a broken gate and an absent device both
    look like 404.
    """
    totp_auth.TOTP.activate(user, totp_auth.generate_totp_secret())
    recovery_codes_auth.RecoveryCodes.activate(user)
    return user


@pytest.fixture
def org_a(db):
    return OrganisationFactory()


@pytest.fixture
def org_b(db):
    return OrganisationFactory()


@pytest.fixture
def product_a(org_a):
    return ProductFactory(organisation=org_a)


@pytest.fixture
def org_member(org_a):
    user = VerifiedUserFactory()
    MembershipFactory(organisation=org_a, user=user)
    return user


@pytest.fixture
def member_other_org(org_b):
    user = VerifiedUserFactory()
    MembershipFactory(organisation=org_b, user=user)
    return user


@pytest.fixture
def reviewer(db):
    """Console access, but not the admin-approve permission (A6 adds that)."""
    return _with_mfa(VerifiedUserFactory(is_staff=True))


@pytest.fixture
def staff_user(db):
    return _with_mfa(VerifiedUserFactory(is_staff=True, is_superuser=True))


@pytest.fixture
def actors(org_member, member_other_org, reviewer, staff_user):
    return {
        ANONYMOUS: None,
        ORG_MEMBER: org_member,
        MEMBER_OTHER_ORG: member_other_org,
        REVIEWER: reviewer,
        STAFF: staff_user,
    }


@pytest.fixture
def context(actors, org_a, org_b, product_a):
    """What a route's `kwargs` callable receives when it builds URL arguments."""
    return {**actors, "org_a": org_a, "org_b": org_b, "product_a": product_a}


@pytest.fixture
def clients(actors):
    """One logged-in test client per actor; anonymous gets a bare client."""
    built = {}
    for name, user in actors.items():
        client = Client()
        if user is not None:
            client.force_login(user)
        built[name] = client
    return built
