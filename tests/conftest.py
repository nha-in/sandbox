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
from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission
from django.test import Client

from sandbox.applications.models import ApplicationDocument
from sandbox.applications.models import ApplicationFormSubmission
from sandbox.applications.models import ApplicationState
from sandbox.applications.tests.factories import ApplicationFactory
from sandbox.organisations.tests.factories import MembershipFactory
from sandbox.organisations.tests.factories import OrganisationFactory
from sandbox.organisations.tests.factories import ProductFactory
from sandbox.users.models import User
from sandbox.users.tests.factories import VerifiedUserFactory

ANONYMOUS = "anonymous"
ORG_MEMBER = "org_member"
MEMBER_OTHER_ORG = "member_other_org"
REVIEWER = "reviewer"
STAFF = "staff"
DOCUMENT_A = "document_a"
MILESTONE_M1 = "milestone_m1"
ROLE = "role"

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
    """On the ABDM review team: may see and opine, may not decide.

    Holds `view_abdm` because permissions are per programme now — a staff user
    on no team sees an empty console, which is correct but makes every route
    row look like a broken gate.
    """
    user = _with_mfa(VerifiedUserFactory(is_staff=True))
    for codename in ("view_abdm", "review_abdm"):
        user.user_permissions.add(Permission.objects.get(codename=codename))
    return User.objects.get(pk=user.pk)


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
    """An evidence document owned by org A, for the org-scoped download row.

    Built through the ORM rather than the service: presigning needs no network,
    so the matrix stays offline and does not depend on a mocked S3.

    Its own product, because the in-flight constraint allows only one live
    application per (product, workflow) and `application` above holds product_a.
    """
    application = ApplicationFactory(
        product=ProductFactory(organisation=org_a),
        applicant=org_member,
        state=ApplicationState.PROVISIONED,
    )
    submission = ApplicationFormSubmission.objects.create(
        application=application,
        form_key="MILESTONE_M1",
        round=application.round,
        data={},
        is_current=True,
        submitted_by=org_member,
    )
    return ApplicationDocument.objects.create(
        submission=submission,
        kind="FUNCTIONAL_TEST_REPORT",
        storage_key=f"applications/{submission.external_id}/{uuid.uuid4()}",
        filename="evidence.pdf",
        content_type="application/pdf",
        size=1024,
        sha256="0" * 64,
        uploaded_by=org_member,
    )


@pytest.fixture
def milestone_m1():
    """The key a milestone URL names. Milestones come from the workflow, so
    there is no row to create — only the segment the route needs."""
    return "m1"


@pytest.fixture
def past_exit(application):
    """A decided exit on the same product, for the read-only exit screen."""
    return ApplicationFactory.create(
        product=application.product,
        applicant=application.applicant,
        workflow_key="ABDM_EXIT",
        state="APPROVED",
        registered=False,
    )


@pytest.fixture
def role(db):
    """A console role for the routes that edit one. Nobody in the matrix holds
    `manage_roles`, which is the point of those rows."""
    return Group.objects.create(name="ABDM review team")


@pytest.fixture
def objects(application, document_a, milestone_m1, role, past_exit):
    """The rows a route's `kwargs` callable can name, in one bundle."""
    return {
        "application": application,
        "past_exit": past_exit,
        DOCUMENT_A: document_a,
        MILESTONE_M1: milestone_m1,
        ROLE: role,
    }


@pytest.fixture
def context(actors, objects):
    """What a route's `kwargs` callable receives when it builds URL arguments.

    Organisations and products are reachable from these objects
    (`application.product.organisation`), so they are not pre-loaded here.
    """
    return {**actors, **objects}


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
