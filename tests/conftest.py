"""Actor fixtures for the route-gate matrix (C3).

Five actors, two organisations. Every URL in the portal is exercised against all
of them by `test_route_gates.py`, so these fixtures are the definition of "who
could be knocking".
"""

from __future__ import annotations

import uuid

import pytest
from allauth.mfa.recovery_codes.internal import auth as recovery_codes_auth
from allauth.mfa.totp.internal import auth as totp_auth
from django.test import Client

from sandbox.applications.models import ApplicationState
from sandbox.applications.tests.factories import ApplicationFactory
from sandbox.declarations.models import Declaration
from sandbox.declarations.models import DeclarationDocument
from sandbox.declarations.models import DeclarationKind
from sandbox.organisations.tests.factories import MembershipFactory
from sandbox.organisations.tests.factories import OrganisationFactory
from sandbox.organisations.tests.factories import ProductFactory
from sandbox.users.tests.factories import VerifiedUserFactory

ANONYMOUS = "anonymous"
ORG_MEMBER = "org_member"
MEMBER_OTHER_ORG = "member_other_org"
REVIEWER = "reviewer"
STAFF = "staff"
DOCUMENT_A = "document_a"

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
def application(product_a, org_member):
    """A submitted application, so console detail and action URLs resolve."""
    return ApplicationFactory(
        product=product_a,
        applicant=org_member,
        state=ApplicationState.SUBMITTED,
    )


@pytest.fixture
def document_a(org_a, org_member):
    """A declaration document owned by org A, for the org-scoped download row.

    Built through the ORM rather than the service: presigning needs no network,
    so the matrix stays offline and does not depend on a mocked S3.

    Its own product, because `UNIQUE (product, kind)` allows only one live
    application per product and `application` above already holds product_a.
    """
    application = ApplicationFactory(
        product=ProductFactory(organisation=org_a),
        applicant=org_member,
        state=ApplicationState.PROVISIONED,
    )
    declaration = Declaration.objects.create(
        application=application,
        kind=DeclarationKind.MILESTONE,
        declared_by=org_member,
    )
    return DeclarationDocument.objects.create(
        declaration=declaration,
        storage_key=f"declarations/{declaration.external_id}/{uuid.uuid4()}",
        filename="evidence.pdf",
        content_type="application/pdf",
        size=1024,
        sha256="0" * 64,
        uploaded_by=org_member,
    )


@pytest.fixture
def context(actors, application, document_a):
    """What a route's `kwargs` callable receives when it builds URL arguments.

    Organisations and products are reachable from these objects
    (`application.product.organisation`), so they are not pre-loaded here.
    """
    return {
        **actors,
        "application": application,
        DOCUMENT_A: document_a,
    }


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
