"""C7 acceptance criteria — the credentials panel.

The tests that matter most here are the negative ones. A panel that shows a
secret is easy; a panel that shows it exactly once, to the right person, and
leaves no copy behind is the whole ticket. Legacy failed all three: it stored
the secret in plaintext in `sd_status.gen_securate` and emailed it as well.

The domain half of C7 is covered in `sandbox/integrations/tests/` — never
persisted, never logged, never in a DTO's repr. What is asserted here is the
HTTP layer built on it (§8.4).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from django.conf import settings
from django.test import Client
from django.utils import timezone

from sandbox.experiences.models import ApplicationAccess
from sandbox.experiences.models import ApplicationEvent
from sandbox.experiences.services import perform_application_action
from sandbox.experiences.tests.factories import review_role_holder
from sandbox.experiences.tests.factories import sandbox_access_under_review
from sandbox.integrations.credentials import take_initial_secret
from sandbox.integrations.models import ProvisionedResource
from sandbox.integrations.models import ProvisionedSystem
from sandbox.notifications.models import Message
from sandbox.organisations.models import Membership
from sandbox.organisations.models import ProvisioningRun
from sandbox.organisations.models import Role
from sandbox.organisations.tests.factories import OrganisationFactory
from sandbox.users.tests.factories import UserFactory


def enable_mfa(user):
    from allauth.mfa.totp.internal import auth  # noqa: PLC0415

    auth.TOTP.activate(user, auth.generate_totp_secret())


pytestmark = pytest.mark.django_db

HTTP_OK = 200
HTTP_BAD_REQUEST = 400
HTTP_NOT_FOUND = 404


@pytest.fixture
def owner(db):
    return UserFactory.create(email="owner@vendor.in")


@pytest.fixture
def reviewer(db):
    user = review_role_holder("decision_maker", email="reviewer@nha.gov.in")
    user.is_staff = True
    user.save(update_fields=["is_staff"])
    enable_mfa(user)
    return user


@pytest.fixture
def provisioned(owner, reviewer, django_capture_on_commit_callbacks):
    """Approved, with the chain the approval schedules actually run."""
    application = sandbox_access_under_review(owner, reviewer)
    with django_capture_on_commit_callbacks(execute=True):
        perform_application_action(
            application=application,
            action_key="approve",
            user=reviewer,
            cleaned_data={
                "approved_milestones": ["m1"],
                "effective_date": timezone.localdate(),
                "certificate_reference": "CERT-2026-1001",
                "note": "Verified.",
            },
        )
    application.refresh_from_db()
    return application


@pytest.fixture
def developer(provisioned):
    """In the organisation and on the application, but not its owner.

    Both halves are needed: membership puts them in the tenant, and an
    `ApplicationAccess` grant is what `visible_to` asks for — rotation is
    refused on the third, `Role.OWNER`.
    """
    user = UserFactory.create(email="dev@vendor.in")
    Membership.objects.create(
        organisation=provisioned.organisation,
        user=user,
        role=Role.DEVELOPER,
    )
    ApplicationAccess.objects.create(
        application=provisioned,
        user=user,
        role_key="applicant_contributor",
        granted_by=provisioned.created_by,
    )
    return user


def signed_in(user) -> Client:
    client = Client()
    client.force_login(user)
    return client


def panel(application) -> str:
    return f"/applications/{application.reference}/credentials/"


def reveal(session, application):
    return session.post(panel(application), {"action": "reveal"})


def rotate(session, application):
    return session.post(panel(application), {"action": "rotate"})


def secret_from(response, application) -> str:
    """The revealed secret, pulled back out of the rendered panel.

    Read from the DOM rather than from the service, because every assertion
    here is about this exact string — the one the integrator actually saw.
    """
    body = response.content.decode()
    marker = 'data-copy="'
    values = []
    index = body.find(marker)
    while index != -1:
        start = index + len(marker)
        values.append(body[start : body.index('"', start)])
        index = body.find(marker, start)
    client_id = ProvisionedResource.objects.get(
        application=application,
        system=ProvisionedSystem.KEYCLOAK,
    ).public_ref
    return next((value for value in values if value != client_id), "")


# Show-once


def test_the_secret_is_shown_once_and_the_panel_is_masked_afterwards(
    owner,
    provisioned,
):
    session = signed_in(owner)

    first = reveal(session, provisioned)
    assert first.status_code == HTTP_OK
    secret = secret_from(first, provisioned)
    assert secret, "the first reveal showed nothing"

    second = reveal(session, provisioned)
    body = second.content.decode()
    assert secret not in body, "the secret came back on a second POST"
    assert "already been shown" in body


def test_the_detail_page_never_carries_the_secret_on_a_get(owner, provisioned):
    """The reveal is a POST precisely so that no GET can burn it: a prefetching
    browser or a crawler following a link would spend the single read on
    nobody's behalf, and the integrator would meet a masked panel they had
    never seen unmasked."""
    session = signed_in(owner)

    page = session.get(f"/applications/{provisioned.reference}/")

    assert page.status_code == HTTP_OK
    assert "Sandbox credentials" in page.content.decode()
    # Still unread: the GET must not have consumed the hand-off.
    assert take_initial_secret(provisioned) is not None


def test_there_is_no_url_a_get_could_burn_the_secret_on(owner, provisioned):
    """Reveal is an action on the panel, not a URL of its own, so history, a
    restored tab and a prefetch all land on the poll and consume nothing.

    Structural rather than behavioural: with one route there is nothing to
    accidentally GET, which is a stronger guarantee than a redirect was.
    """
    session = signed_in(owner)

    assert session.get(panel(provisioned)).status_code == HTTP_OK
    assert take_initial_secret(provisioned) is not None


def test_a_post_with_no_known_action_does_nothing(owner, provisioned):
    session = signed_in(owner)

    response = session.post(panel(provisioned), {"action": "burn"})

    assert response.status_code == HTTP_BAD_REQUEST
    assert take_initial_secret(provisioned) is not None


def test_polling_the_panel_cannot_consume_the_handoff(owner, provisioned):
    session = signed_in(owner)

    for _ in range(3):
        assert session.get(panel(provisioned)).status_code == HTTP_OK

    assert take_initial_secret(provisioned) is not None


# Polling


def test_the_panel_polls_while_provisioning_and_stops_when_the_run_ends(
    owner,
    provisioned,
):
    """The trigger has to stop rendering itself, or every finished integrator
    keeps a request every few seconds running forever."""
    session = signed_in(owner)

    assert "hx-trigger" not in session.get(panel(provisioned)).content.decode()

    run = provisioned.provisioning_runs.order_by("-started_at").first()
    run.status = ProvisioningRun.Status.RUNNING
    run.finished_at = None
    run.save(update_fields=["status", "finished_at"])

    assert "hx-trigger" in session.get(panel(provisioned)).content.decode()


# Rotation


def test_an_owner_can_rotate_and_sees_the_new_secret_once(owner, provisioned):
    session = signed_in(owner)

    response = rotate(session, provisioned)

    assert response.status_code == HTTP_OK
    assert "you will not see it again" in response.content.decode().lower()
    assert ApplicationEvent.objects.filter(
        application=provisioned,
        action_key="credentials.rotated",
        actor=owner,
    ).exists()


def test_rotation_leaves_no_readable_copy_of_either_secret(owner, provisioned):
    """The old one is dead in Keycloak; the new one was never parked."""
    session = signed_in(owner)

    rotate(session, provisioned)

    assert take_initial_secret(provisioned) is None
    row = ProvisionedResource.objects.get(
        application=provisioned,
        system=ProvisionedSystem.KEYCLOAK,
    )
    assert row.secret_ref == ""


def test_a_developer_may_reveal_but_not_rotate(developer, provisioned):
    """The access decision C7 asks for, recorded as a test rather than prose:
    the credential is what a developer is here to use, but rotation breaks a
    live integration and belongs to the accountable role."""
    session = signed_in(developer)

    revealed = reveal(session, provisioned)
    assert "you will not see it again" in revealed.content.decode().lower()

    refused = rotate(session, provisioned)
    assert "only an owner" in refused.content.decode().lower()


def test_rotation_before_provisioning_is_refused_rather_than_crashing(owner, reviewer):
    application = sandbox_access_under_review(owner, reviewer)
    session = signed_in(owner)

    response = rotate(session, application)

    assert "no credentials to rotate" in response.content.decode().lower()


# Nobody else


def test_another_organisation_gets_a_404_not_a_403(provisioned):
    """A vendor with a tenant of their own: the interesting case, because
    `OrganisationMixin` lets them past and the application queryset does not."""
    stranger = UserFactory.create(email="stranger@elsewhere.in")
    Membership.objects.create(
        organisation=OrganisationFactory(onboarded=True),
        user=stranger,
        role=Role.OWNER,
    )
    session = signed_in(stranger)

    assert session.get(panel(provisioned)).status_code == HTTP_NOT_FOUND
    assert reveal(session, provisioned).status_code == HTTP_NOT_FOUND
    assert rotate(session, provisioned).status_code == HTTP_NOT_FOUND


def test_staff_have_no_reveal_route_at_all(reviewer, provisioned):
    """Not "staff are refused" — there is no staff-facing path to a secret in
    the URLconf, which is the property worth asserting."""
    session = signed_in(reviewer)

    console = session.get(f"/staff/applications/{provisioned.reference}/")
    body = console.content.decode()

    assert console.status_code == HTTP_OK
    assert "reveal" not in body.lower()
    assert "/credentials/" not in body
    assert take_initial_secret(provisioned) is not None


# The secret does not leak sideways


def test_the_secret_appears_in_no_event_notification_or_ledger_column(
    owner,
    provisioned,
):
    session = signed_in(owner)
    response = reveal(session, provisioned)
    secret = secret_from(response, provisioned)
    assert secret, "the reveal rendered nothing that looks like a secret"

    haystacks = [
        " ".join(
            f"{event.title}{event.description}{event.payload}"
            for event in ApplicationEvent.objects.all()
        ),
        " ".join(str(message.params) for message in Message.objects.all()),
        " ".join(
            f"{row.external_ref}{row.public_ref}{row.secret_ref}"
            for row in ProvisionedResource.objects.all()
        ),
    ]
    for haystack in haystacks:
        assert secret not in haystack


def test_the_quickstart_never_interpolates_a_secret():
    """A snippet is a thing people paste into chat logs and issue trackers.

    Asserted against the template source, not a render: the secret exists for
    one response only, so a passing render proves nothing about the round trip
    where it does exist.
    """
    source = (
        Path(settings.APPS_DIR)
        / "templates"
        / "experiences"
        / "partials"
        / "quickstart.html"
    ).read_text()

    for forbidden in ("revealed_secret", 'client_secret="{{', "initial_secret"):
        assert forbidden not in source, (
            f"quickstart.html references {forbidden}; the snippet must say "
            "<your client secret> and never carry the real one"
        )
