"""C7 acceptance criteria — the credentials panel.

The tests that matter most here are the negative ones. A panel that shows a
secret is easy; a panel that shows it exactly once, to the right person, and
leaves no copy behind is the whole ticket. Legacy failed all three: it stored
the secret in plaintext in `sd_status.gen_securate` and emailed it as well.
"""

from __future__ import annotations

import pytest
from allauth.mfa.recovery_codes.internal import auth as recovery_codes_auth
from allauth.mfa.totp.internal import auth as totp_auth
from django.contrib.auth.models import Permission
from django.urls import reverse

from sandbox.applications.models import ApplicationState
from sandbox.applications.tests.factories import ApplicationFactory
from sandbox.audit.models import AuditEvent
from sandbox.integrations.credentials import take_initial_secret
from sandbox.integrations.hooks import register_workflow_hooks
from sandbox.integrations.models import ProvisionedResource
from sandbox.integrations.models import ProvisionedSystem
from sandbox.notifications import hooks as notification_hooks
from sandbox.notifications.models import Message
from sandbox.organisations.mixins import organisation_query
from sandbox.organisations.models import MembershipRole
from sandbox.organisations.tests.factories import MembershipFactory
from sandbox.users.models import User
from sandbox.users.tests.factories import VerifiedUserFactory
from sandbox.workflow import engine as workflow_engine
from sandbox.workflow.engine import transition

pytestmark = pytest.mark.django_db

HTTP_OK = 200
HTTP_NOT_FOUND = 404


@pytest.fixture(autouse=True)
def _hooks():
    workflow_engine.clear_hooks()
    register_workflow_hooks()
    notification_hooks.register_workflow_hooks()
    yield
    workflow_engine.clear_hooks()


@pytest.fixture
def application():
    return ApplicationFactory.create()


@pytest.fixture
def owner(application):
    user = VerifiedUserFactory.create()
    MembershipFactory.create(
        organisation=application.product.organisation,
        user=user,
        role=MembershipRole.OWNER,
    )
    return user


@pytest.fixture
def developer(application):
    user = VerifiedUserFactory.create()
    MembershipFactory.create(
        organisation=application.product.organisation,
        user=user,
        role=MembershipRole.DEVELOPER,
    )
    return user


def _staff(*codenames: str) -> User:
    user = VerifiedUserFactory.create(is_staff=True)
    # VerificationRequiredMiddleware sends a staff user with no device to TOTP
    # setup, which would make every assertion below a test of that redirect.
    totp_auth.TOTP.activate(user, totp_auth.generate_totp_secret())
    recovery_codes_auth.RecoveryCodes.activate(user)
    for codename in codenames:
        user.user_permissions.add(Permission.objects.get(codename=codename))
    return User.objects.get(pk=user.pk)


@pytest.fixture
def provisioned(application, owner, django_capture_on_commit_callbacks):
    transition(application=application, action="SUBMIT", actor=owner)
    with django_capture_on_commit_callbacks(execute=True):
        transition(
            application=application,
            action="APPROVE",
            actor=_staff("approve_application"),
        )
    application.refresh_from_db()
    assert application.state == ApplicationState.PROVISIONED
    return application


def _query(application) -> str:
    return f"?{organisation_query(application.product.organisation)}"


def _credentials_page(application) -> str:
    return reverse(
        "applications:credentials",
        kwargs={"external_id": application.external_id},
    ) + _query(application)


def _overview(application) -> str:
    return reverse(
        "applications:overview",
        kwargs={"external_id": application.external_id},
    ) + _query(application)


def _reveal(application) -> str:
    url = reverse(
        "applications:reveal_credentials",
        kwargs={"external_id": application.external_id},
    )
    return url + _query(application)


def _rotate(application) -> str:
    url = reverse(
        "applications:rotate_credentials",
        kwargs={"external_id": application.external_id},
    )
    return url + _query(application)


def _client_for(user, client):
    client.force_login(user)
    return client


# Show-once


def test_the_secret_is_shown_once_and_the_panel_is_masked_afterwards(
    client,
    owner,
    provisioned,
):
    session = _client_for(owner, client)

    first = session.post(_reveal(provisioned))
    assert first.status_code == HTTP_OK
    secret = _secret_from_response(first)
    assert secret, "the first reveal showed nothing"

    second = session.post(_reveal(provisioned))
    body = second.content.decode()
    assert secret not in body, "the secret came back on a second POST"
    assert "••••" in body


def test_the_credentials_page_never_carries_the_secret_on_a_get(
    client,
    owner,
    provisioned,
):
    """The reveal is a POST precisely so that no GET can burn it: a prefetching
    browser or a crawler following a link would spend the single read on
    nobody's behalf, and the integrator would meet a masked panel they had
    never seen unmasked."""
    session = _client_for(owner, client)

    assert session.get(_credentials_page(provisioned)).status_code == HTTP_OK
    # Still unread: the GET must not have consumed the hand-off.
    assert take_initial_secret(provisioned) is not None


def test_a_get_on_the_reveal_route_redirects_and_consumes_nothing(
    client,
    owner,
    provisioned,
):
    """History, a restored tab or a bookmark can all land a GET here. It must
    not burn the single read, and it must not be a 405 dead end either."""
    session = _client_for(owner, client)

    response = session.get(_reveal(provisioned))
    assert response.status_code == 302  # noqa: PLR2004
    assert str(provisioned.external_id) in response.headers["Location"]
    assert take_initial_secret(provisioned) is not None


def test_polling_the_panel_cannot_consume_the_handoff(client, owner, provisioned):
    session = _client_for(owner, client)
    url = reverse(
        "applications:credentials_panel",
        kwargs={"external_id": provisioned.external_id},
    ) + _query(provisioned)

    for _ in range(3):
        assert session.get(url).status_code == HTTP_OK

    assert take_initial_secret(provisioned) is not None


# Polling


def test_the_panel_polls_while_provisioning_and_stops_at_a_terminal_state(
    client,
    owner,
    provisioned,
):
    """The trigger has to stop rendering itself, or every finished integrator
    keeps a request every few seconds running forever."""
    session = _client_for(owner, client)
    url = reverse(
        "applications:credentials_panel",
        kwargs={"external_id": provisioned.external_id},
    ) + _query(provisioned)

    assert "hx-trigger" not in session.get(url).content.decode()

    provisioned.state = ApplicationState.PROVISIONING
    provisioned.save(update_fields=["state"])
    assert "hx-trigger" in session.get(url).content.decode()


# Rotation


def test_an_owner_can_rotate_and_sees_the_new_secret_once(
    client,
    owner,
    provisioned,
):
    session = _client_for(owner, client)

    response = session.post(_rotate(provisioned))
    assert response.status_code == HTTP_OK
    assert "you will not see it again" in response.content.decode().lower()

    assert AuditEvent.objects.filter(
        action="credentials.rotated",
        actor=owner,
    ).exists()


def test_rotation_leaves_no_readable_copy_of_either_secret(
    client,
    owner,
    provisioned,
):
    """The old one is dead in Keycloak; the new one was never parked."""
    session = _client_for(owner, client)
    session.post(_rotate(provisioned))

    assert take_initial_secret(provisioned) is None
    row = ProvisionedResource.objects.get(
        application=provisioned,
        system=ProvisionedSystem.KEYCLOAK,
    )
    assert row.secret_ref == ""


def test_a_developer_may_reveal_but_not_rotate(client, developer, provisioned):
    """The access decision C7 asks for, recorded as a test rather than prose:
    the credential is what a developer is here to use, but rotation breaks a
    live integration and belongs to the accountable role."""
    session = _client_for(developer, client)

    revealed = session.post(_reveal(provisioned))
    assert "you will not see it again" in revealed.content.decode().lower()

    refused = session.post(_rotate(provisioned), follow=True)
    assert "only an owner" in refused.content.decode().lower()


def test_rotation_before_provisioning_is_refused_rather_than_crashing(
    client,
    owner,
    application,
):
    session = _client_for(owner, client)
    response = session.post(_rotate(application), follow=True)
    assert "no credentials to rotate" in response.content.decode().lower()


# Nobody else


def test_another_organisation_gets_a_404_not_a_403(client, provisioned):
    stranger = VerifiedUserFactory.create()
    MembershipFactory.create(user=stranger)
    session = _client_for(stranger, client)

    for url in (_reveal(provisioned), _rotate(provisioned)):
        assert session.post(url).status_code == HTTP_NOT_FOUND


def test_staff_have_no_reveal_route_at_all(client, provisioned):
    """Not "staff are refused" — there is no staff-facing path to a secret in
    the URLconf, which is the property worth asserting."""
    session = _client_for(_staff("approve_application"), client)

    # The integrator routes 404 for staff: they hold no membership.
    assert session.post(_reveal(provisioned)).status_code == HTTP_NOT_FOUND

    detail = session.get(
        reverse(
            "console:application_detail",
            kwargs={"external_id": provisioned.external_id},
        ),
    )
    body = detail.content.decode()
    assert "Provisioning" in body
    assert "reveal" not in body.lower()
    assert take_initial_secret(provisioned) is not None


# The secret does not leak sideways


def test_the_secret_appears_in_no_audit_row_notification_or_ledger_column(
    client,
    owner,
    provisioned,
):
    session = _client_for(owner, client)
    response = session.post(_reveal(provisioned))
    secret = _secret_from_response(response)
    assert secret, "the reveal rendered nothing that looks like a secret"

    haystacks = [
        " ".join(str(event.data) for event in AuditEvent.objects.all()),
        " ".join(str(message.params) for message in Message.objects.all()),
        " ".join(
            f"{row.external_ref}{row.public_ref}{row.secret_ref}"
            for row in ProvisionedResource.objects.all()
        ),
    ]
    for haystack in haystacks:
        assert secret not in haystack


def _secret_from_response(response) -> str:
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
    # The client id is copyable too; the secret is the one that is not it.
    client_id = ProvisionedResource.objects.get(
        application=response.context["application"],
        system=ProvisionedSystem.KEYCLOAK,
    ).public_ref
    return next((value for value in values if value != client_id), "")
