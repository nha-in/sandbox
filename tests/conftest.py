"""Actor fixtures for the route-gate matrix (C3).

Five actors, two organisations. Every named URL in the portal is exercised
against all of them by `test_route_gates.py`, so these fixtures are the
definition of "who could be knocking".

The set at `552692c^` was the same shape against `sandbox/applications/`, which
step 1 deleted. This one is rebuilt on the engine: an `ApplicationInstance`
rather than an `Application`, and NHA's authority as a `ReviewRole` row rather
than a Django permission (§5).
"""

from __future__ import annotations

import pytest
from allauth.account.models import EmailAddress
from allauth.mfa.adapter import get_adapter as get_mfa_adapter
from allauth.mfa.recovery_codes.internal import auth as recovery_codes_auth
from allauth.mfa.totp.internal import auth as totp_auth
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from sandbox.events.tests.factories import EventFactory
from sandbox.experiences.models import ApplicationAccess
from sandbox.experiences.models import ApplicationAttachment
from sandbox.experiences.models import ApplicationFormSubmission
from sandbox.experiences.models import ApplicationQueryThread
from sandbox.experiences.models import ReviewRole
from sandbox.experiences.models import ReviewRoleAssignment
from sandbox.experiences.services import create_application
from sandbox.experiences.services import perform_application_action
from sandbox.experiences.tests.factories import gate_data
from sandbox.organisations.models import Membership
from sandbox.organisations.models import Role
from sandbox.organisations.tests.factories import InvitationFactory
from sandbox.organisations.tests.factories import OrganisationFactory
from sandbox.support.models import Ticket
from sandbox.users.tests.factories import UserFactory

#: Awaiting rewrite in plan 12 §8.4. Delete an entry as its module is dealt
#: with; the list reaching empty is what clears the debt.
collect_ignore = [
    # delete: the concepts they test are gone (§8.4)
    "test_enrollment_wizard.py",
    "test_merge_production_dotenvs_in_dotenv.py",
    # build the subject first, then port (§8.4)
    "test_credentials_panel.py",
    "test_dashboard.py",
    "test_navigation.py",
    # rewrite against the arriving theme (§4.1)
    "test_stylesheet.py",
    "test_template_syntax.py",
]

APPLICATION_TYPE = "abdm_production_access"

ANONYMOUS = "anonymous"
ORG_MEMBER = "org_member"
MEMBER_OTHER_ORG = "member_other_org"
REVIEWER = "reviewer"
STAFF = "staff"

ACTORS = (ANONYMOUS, ORG_MEMBER, MEMBER_OTHER_ORG, REVIEWER, STAFF)
STAFF_ACTORS = (REVIEWER, STAFF)

#: Keys into the `context` bundle a route's `kwargs` callable receives.
APPLICATION = "application"
ATTACHMENT = "attachment"
EVENT = "event"
INVITATION = "invitation"
MEMBERSHIP = "membership"
QUERY = "query"
TICKET = "ticket"


def verified_user(**kwargs):
    """`ACCOUNT_EMAIL_VERIFICATION` is mandatory, so an unverified account is
    bounced before any route gate is reached."""
    user = UserFactory(**kwargs)
    EmailAddress.objects.get_or_create(
        user=user,
        email=user.email,
        defaults={"verified": True, "primary": True},
    )
    return user


def _with_mfa(user):
    """Staff without a TOTP device are bounced by `StaffMfaRequiredMiddleware`.

    Recovery codes too, so the matrix can assert that a user who *holds* an MFA
    resource reaches its URL — otherwise a broken gate and an absent device
    both look like 404.
    """
    if not get_mfa_adapter().is_mfa_enabled(user):
        totp_auth.TOTP.activate(user, totp_auth.generate_totp_secret())
    recovery_codes_auth.RecoveryCodes.activate(user)
    return user


@pytest.fixture
def org_a(db):
    return OrganisationFactory(onboarded=True, name="Sunrise Health Systems")


@pytest.fixture
def org_b(db):
    return OrganisationFactory(onboarded=True, name="Northwind Digital Health")


@pytest.fixture
def org_member(org_a):
    user = verified_user(email="member@vendor.in")
    Membership.objects.create(organisation=org_a, user=user, role=Role.OWNER)
    return user


@pytest.fixture
def member_other_org(org_b):
    user = verified_user(email="other@vendor.in")
    Membership.objects.create(organisation=org_b, user=user, role=Role.OWNER)
    return user


@pytest.fixture
def reviewer(db):
    """NHA's review team, by standing role rather than per-application grant.

    §5 moved platform authority out of the registry and into `ReviewRole` rows,
    so a reviewer holds no Django permission — a staff account with no
    assignment sees an empty console, which is correct but would make every
    console row look like a broken gate.
    """
    user = _with_mfa(
        verified_user(email="reviewer@nha.gov.in", is_staff=True),
    )
    ReviewRoleAssignment.objects.create(
        user=user,
        role=ReviewRole.objects.get(key="decision_maker"),
    )
    return user


@pytest.fixture
def staff_user(db):
    return _with_mfa(
        verified_user(
            email="superuser@nha.gov.in",
            is_staff=True,
            is_superuser=True,
        ),
    )


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
def clients(actors):
    result = {}
    for name, user in actors.items():
        client = Client()
        if user is not None:
            client.force_login(user)
        result[name] = client
    return result


@pytest.fixture
def application(org_a, org_member, reviewer):
    """Under review, so both the vendor and the console rows resolve."""
    instance = create_application(
        application_type=APPLICATION_TYPE,
        organisation=org_a,
        user=org_member,
    )
    from sandbox.experiences.registry import registry  # noqa: PLC0415

    for form_definition in registry.get(APPLICATION_TYPE).forms:
        if not form_definition.required:
            continue
        ApplicationFormSubmission.objects.create(
            application=instance,
            form_key=form_definition.key,
            data=gate_data().get(form_definition.key, {}),
            submitted_by=org_member,
        )
    perform_application_action(
        application=instance,
        action_key="submit",
        user=org_member,
    )
    perform_application_action(
        application=instance,
        action_key="start_review",
        user=reviewer,
    )
    instance.refresh_from_db()
    return instance


@pytest.fixture
def query(application, org_member):
    return ApplicationQueryThread.objects.create(
        application=application,
        subject="A question about the evidence",
        opened_by=org_member,
    )


@pytest.fixture
def attachment(application, org_member):
    submission = application.submissions.filter(is_current=True).first()
    return ApplicationAttachment.objects.create(
        submission=submission,
        field_key="certificate_documents",
        file=SimpleUploadedFile("evidence.pdf", b"evidence"),
        original_name="evidence.pdf",
        content_type="application/pdf",
        size=8,
        uploaded_by=org_member,
    )


@pytest.fixture
def membership(org_a, org_member):
    """A second member, so the remove and role rows target someone who is not
    the only owner."""
    user = verified_user(email="colleague@vendor.in")
    return Membership.objects.create(
        organisation=org_a,
        user=user,
        role=Role.DEVELOPER,
    )


@pytest.fixture
def invitation(org_a, org_member):
    return InvitationFactory(organisation=org_a, invited_by=org_member)


@pytest.fixture
def ticket(org_a, org_member):
    return Ticket.objects.create(
        organisation=org_a,
        subject="Sandbox credentials are not arriving",
        created_by=org_member,
    )


@pytest.fixture
def event(db):
    return EventFactory(published=True)


@pytest.fixture
def access_grant(application, membership):
    """Someone other than the owner holding access, for the remove rows."""
    return ApplicationAccess.objects.create(
        application=application,
        user=membership.user,
        role_key="applicant_viewer",
        granted_by=application.created_by,
    )


@pytest.fixture
def objects(  # noqa: PLR0913, PLR0917 - one fixture per row a URL can name
    application,
    query,
    attachment,
    membership,
    invitation,
    ticket,
    event,
):
    """The rows a route's `kwargs` callable can name, in one bundle."""
    return {
        APPLICATION: application,
        QUERY: query,
        ATTACHMENT: attachment,
        MEMBERSHIP: membership,
        INVITATION: invitation,
        TICKET: ticket,
        EVENT: event,
    }


@pytest.fixture
def context(actors, objects, access_grant):
    """What a route's `kwargs` callable receives when it builds URL arguments.

    `access_grant` is named by no row; it exists so the access-removal URLs
    point at somebody who actually holds a grant.
    """
    assert access_grant.pk
    return {**actors, **objects}
