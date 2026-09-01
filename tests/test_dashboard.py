"""Dashboard behaviour (C6).

The load-bearing test is `test_every_state_renders`: 13 states, and a dashboard
that falls through to a blank page on one of them is the kind of bug nobody
notices until an integrator is sitting on that state.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from sandbox.applications.models import ApplicationState
from sandbox.applications.selectors import EDGE_STATES
from sandbox.applications.selectors import JOURNEY_LABELS
from sandbox.applications.selectors import PENDING_STATES
from sandbox.applications.selectors import journey_for
from sandbox.applications.tests.factories import ApplicationFactory
from sandbox.organisations.tests.factories import MembershipFactory
from sandbox.organisations.tests.factories import ProductFactory
from sandbox.users.tests.factories import VerifiedUserFactory

pytestmark = pytest.mark.django_db

HTTP_OK = 200
HTTP_NOT_FOUND = 404


@pytest.fixture
def member_client(client, org_member):
    client.force_login(org_member)
    return client


def _overview(client, application) -> object:
    return client.get(
        reverse(
            "applications:overview",
            kwargs={"external_id": application.external_id},
        ),
    )


# --- the mapping ------------------------------------------------------------


@pytest.mark.parametrize("state", ApplicationState.values)
def test_every_state_has_a_place_on_the_track(state):
    """No state may fall through to an empty stepper *and* no banner."""
    steps = journey_for(state)

    assert len(steps) == len(JOURNEY_LABELS)
    currents = [step for step in steps if step.status == "current"]
    if state in EDGE_STATES:
        assert not currents, f"{state} is an edge state; it has no position"
    else:
        assert len(currents) == 1, f"{state} must sit at exactly one step"


def test_steps_before_the_current_one_are_done():
    steps = journey_for(ApplicationState.PROVISIONED)

    assert [step.status for step in steps[:-1]] == ["done"] * (len(steps) - 1)
    assert steps[-1].status == "current"


# --- the page ---------------------------------------------------------------


@pytest.mark.parametrize("state", ApplicationState.values)
def test_every_state_renders(member_client, product_a, org_member, state):
    application = ApplicationFactory(
        product=product_a,
        applicant=org_member,
        state=state,
    )

    response = _overview(member_client, application)

    assert response.status_code == HTTP_OK
    body = response.content.decode()
    assert response.context["hint_title"], f"{state} has no guidance"
    # Either a track or a banner, never a blank card.
    assert ("aria-label" in body) or ("ui-alert" in body)


def test_no_application_offers_the_wizard(member_client):
    """The empty state belongs to the list now: with applications scoped by URL
    there is no per-application page to land on when there are none."""
    response = member_client.get(reverse("applications:index"))

    assert response.status_code == HTTP_OK
    assert response.context["groups"] == []
    assert reverse("applications:step_product") in response.content.decode()


def test_the_list_ignores_exits(member_client, product_a, org_member):
    """An exit is an application, but not one this list can describe: it has no
    registration form, and asking it for one used to 500 the whole page."""
    enrollment = ApplicationFactory(
        product=product_a,
        applicant=org_member,
        state=ApplicationState.PROVISIONED,
    )
    ApplicationFactory(
        product=product_a,
        applicant=org_member,
        workflow_key="ABDM_EXIT",
        state="UNDER_REVIEW",
        registered=False,
    )

    response = member_client.get(reverse("applications:index"))

    assert response.status_code == HTTP_OK
    listed = [
        entry["row"].application
        for group in response.context["groups"]
        for entry in group["rows"]
    ]
    assert listed == [enrollment]


def test_a_rejected_application_lets_you_start_again(
    member_client,
    product_a,
    org_member,
):
    """REJECTED and WITHDRAWN free the (product, kind) slot, so the CTA returns."""
    application = ApplicationFactory(
        product=product_a,
        applicant=org_member,
        state=ApplicationState.REJECTED,
    )

    response = _overview(member_client, application)

    assert response.context["can_start_new"] is True


def test_a_live_application_does_not_offer_a_second(
    member_client,
    product_a,
    org_member,
):
    application = ApplicationFactory(
        product=product_a,
        applicant=org_member,
        state=ApplicationState.SUBMITTED,
    )

    response = _overview(member_client, application)

    assert response.context["can_start_new"] is False


# --- polling ----------------------------------------------------------------


@pytest.mark.parametrize("state", sorted(PENDING_STATES))
def test_pending_states_poll(member_client, product_a, org_member, state):
    application = ApplicationFactory(
        product=product_a,
        applicant=org_member,
        state=state,
    )

    response = _overview(member_client, application)

    assert response.context["should_poll"] is True
    assert "hx-trigger" in response.content.decode()


@pytest.mark.parametrize(
    "state",
    [ApplicationState.PROVISIONED, ApplicationState.SANDBOX_APPROVED],
)
def test_settled_states_stop_polling(member_client, product_a, org_member, state):
    """Left running, every finished application would hammer the server forever."""
    application = ApplicationFactory(
        product=product_a,
        applicant=org_member,
        state=state,
    )

    response = _overview(member_client, application)

    assert response.context["should_poll"] is False
    assert "hx-trigger" not in response.content.decode()


def test_the_status_fragment_tells_the_same_truth_without_htmx(
    member_client,
    product_a,
    org_member,
):
    """The partial is a fragment of the page, not a second source of truth."""
    application = ApplicationFactory(
        product=product_a,
        applicant=org_member,
        state=ApplicationState.SUBMITTED,
    )

    fragment = member_client.get(
        reverse(
            "applications:application_status",
            kwargs={"external_id": application.external_id},
        ),
    )

    assert fragment.status_code == HTTP_OK
    assert fragment.context["should_poll"] is True
    assert (
        fragment.context["hint_title"]
        == _overview(member_client, application).context["hint_title"]
    )


# --- org scoping ------------------------------------------------------------


def test_a_member_never_sees_another_organisations_application(
    client,
    product_a,
    org_member,
    org_b,
):
    """The application is named in the URL now, so scoping is what stops an
    outsider reading it — and it 404s rather than 403s, because a 403 would
    confirm the application exists."""
    application = ApplicationFactory(
        product=product_a,
        applicant=org_member,
        state="SUBMITTED",
    )
    outsider = VerifiedUserFactory.create()
    MembershipFactory.create(organisation=org_b, user=outsider)
    ProductFactory.create(organisation=org_b)
    client.force_login(outsider)

    response = _overview(client, application)

    assert response.status_code == HTTP_NOT_FOUND
