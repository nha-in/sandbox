"""Enrolment wizard walk-throughs (C4).

The load-bearing test is `test_full_walk_without_javascript`: the whole journey
is plain POST + redirect, so htmx can be switched off entirely and enrolment
still works. Everything else here guards a specific failure the legacy portal
had — a lost draft, an unmentioned validation error, a second live application.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from sandbox.applications.models import Application
from sandbox.applications.models import ApplicationKind
from sandbox.applications.models import ApplicationState
from sandbox.applications.schemas.sandbox import IntegrationIntent
from sandbox.applications.schemas.sandbox import SolutionType
from sandbox.applications.services import create_draft
from sandbox.organisations.tests.factories import MembershipFactory
from sandbox.organisations.tests.factories import ProductFactory
from sandbox.users.tests.factories import UserFactory
from sandbox.workflow.machine import Action
from sandbox.workflow.services import record_review
from sandbox.workflow.services import transition

pytestmark = pytest.mark.django_db

HTTP_OK = 200
HTTP_FOUND = 302

DETAILS_POST = {
    "solution_types": [SolutionType.EUA],
    "integration_intents": [IntegrationIntent.values[0]],
    "use_case_narrative": "Linking care records for a district hospital.",
}


@pytest.fixture
def member_client(client, org_member):
    client.force_login(org_member)
    return client


def _org_url(name: str, organisation, **kwargs) -> str:
    """Every wizard link names its tenant now that the session no longer does."""
    return f"{reverse(name, kwargs=kwargs)}?org={organisation.external_id}"


def test_full_walk_without_javascript(member_client, org_a, org_member):
    """No htmx headers anywhere: every step is a real form post."""
    response = member_client.post(
        reverse("applications:step_product"),
        {"product": "", "new_product_name": "Care Bridge"},
    )
    assert response.status_code == HTTP_FOUND

    application = Application.objects.get(product__organisation=org_a)
    assert application.state == ApplicationState.DRAFT
    assert application.payload == {"schema_version": 1, "data": {}}
    assert response["Location"] == _org_url(
        "applications:step_details",
        org_a,
        external_id=application.external_id,
    )

    response = member_client.post(response["Location"], DETAILS_POST)
    assert response.status_code == HTTP_FOUND

    review_url = _org_url(
        "applications:step_review",
        org_a,
        external_id=application.external_id,
    )
    assert response["Location"] == review_url

    application.refresh_from_db()
    assert application.payload["schema_version"] == 1
    assert (
        application.payload["data"]["use_case_narrative"]
        == (DETAILS_POST["use_case_narrative"])
    )

    assert member_client.get(review_url).status_code == HTTP_OK

    response = member_client.post(review_url)
    assert response.status_code == HTTP_FOUND

    application.refresh_from_db()
    assert application.state == ApplicationState.SUBMITTED


def test_a_half_finished_draft_survives_the_browser_closing(
    member_client,
    org_a,
    org_member,
):
    """The whole point of a draft: stop mid-form, come back, answers intact."""
    member_client.post(
        reverse("applications:step_product"),
        {"product": "", "new_product_name": "Care Bridge"},
    )
    application = Application.objects.get(product__organisation=org_a)
    url = reverse(
        "applications:step_details",
        kwargs={"external_id": application.external_id},
    )

    partial = {"use_case_narrative": "Half a thought about linking records"}
    response = member_client.post(url, {**partial, "action": "save"})
    assert response.status_code == HTTP_FOUND

    application.refresh_from_db()
    assert application.state == ApplicationState.DRAFT
    assert (
        application.payload["data"]["use_case_narrative"]
        == (partial["use_case_narrative"])
    )

    # ...and it comes back pre-filled
    form = member_client.get(url).context["form"]
    assert form.initial["use_case_narrative"] == partial["use_case_narrative"]


def test_an_incomplete_draft_cannot_be_submitted(member_client, org_a, org_member):
    """Validation moved to SUBMIT, so it has to actually bite there."""
    member_client.post(
        reverse("applications:step_product"),
        {"product": "", "new_product_name": "Care Bridge"},
    )
    application = Application.objects.get(product__organisation=org_a)
    review_url = _org_url(
        "applications:step_review",
        org_a,
        external_id=application.external_id,
    )

    response = member_client.post(review_url, follow=True)

    assert response.status_code == HTTP_OK
    assert any("required" in str(m).lower() for m in response.context["messages"])
    application.refresh_from_db()
    assert application.state == ApplicationState.DRAFT


def test_details_step_reports_payload_errors_as_form_errors(
    member_client,
    product_a,
    org_member,
):
    application = create_draft(
        organisation=product_a.organisation,
        product=product_a,
        applicant=org_member,
        kind=ApplicationKind.SANDBOX,
        data=DETAILS_POST,
    )
    url = reverse(
        "applications:step_details",
        kwargs={"external_id": application.external_id},
    )
    response = member_client.post(url, {"use_case_narrative": ""})

    assert response.status_code == HTTP_OK
    assert response.context["form"].errors
    application.refresh_from_db()
    assert (
        application.payload["data"]["use_case_narrative"]
        == (DETAILS_POST["use_case_narrative"])
    )


def test_entry_resumes_the_draft_in_flight(member_client, product_a, org_member):
    application = create_draft(
        organisation=product_a.organisation,
        product=product_a,
        applicant=org_member,
        kind=ApplicationKind.SANDBOX,
        data=DETAILS_POST,
    )
    response = member_client.get(reverse("applications:new"))

    assert response["Location"] == _org_url(
        "applications:step_details",
        product_a.organisation,
        external_id=application.external_id,
    )


def test_product_step_hides_products_with_a_live_application(
    member_client,
    application,
    org_a,
):
    """The one-live-application rule is enforced by the choices offered, so the
    partial-unique constraint can never surface as a 500."""
    free_product = ProductFactory(organisation=org_a)

    response = member_client.get(reverse("applications:step_product"))

    queryset = response.context["form"].fields["product"].queryset
    assert application.product not in queryset
    assert free_product in queryset


def test_product_step_drops_the_picker_when_nothing_is_selectable(
    member_client,
    application,
):
    """Filing for a second product when every product is already in flight: an
    empty dropdown asks nothing, so the form only offers a name."""
    response = member_client.get(reverse("applications:step_product"))

    form = response.context["form"]
    assert "product" not in form.fields
    assert form.fields["new_product_name"].required


def test_sent_back_application_is_editable_again(
    member_client,
    application,
    org_member,
    staff_user,
):
    record_review(
        application=application,
        reviewer=staff_user,
        decision=Action.SEND_BACK,
        comment="Narrative is too thin.",
    )
    transition(
        application=application,
        action=Action.SEND_BACK,
        actor=staff_user,
    )

    url = reverse(
        "applications:step_details",
        kwargs={"external_id": application.external_id},
    )
    response = member_client.get(url)
    assert response.status_code == HTTP_OK
    assert response.context["editable"]

    response = member_client.post(url, DETAILS_POST)
    assert response.status_code == HTTP_FOUND

    application.refresh_from_db()
    assert application.state == ApplicationState.SENT_BACK


def test_a_locked_application_offers_the_read_only_view_not_an_editor(
    member_client,
    application,
):
    """The editor used to render in full for a submitted application, under a
    line saying it could no longer be edited."""
    url = _org_url(
        "applications:step_details",
        application.product.organisation,
        external_id=application.external_id,
    )

    response = member_client.get(url)

    assert response.status_code == HTTP_FOUND
    assert "/review/" in response["Location"]


def test_a_refused_save_never_reports_success(
    member_client,
    application,
    org_a,
):
    """`update_draft` always refused this write, but the save path ignored the
    refusal and flashed "Draft saved." over a payload it had not touched."""
    url = _org_url(
        "applications:step_details",
        org_a,
        external_id=application.external_id,
    )
    before = dict(application.payload["data"])

    response = member_client.post(
        url,
        {**DETAILS_POST, "action": "save"},
        follow=True,
    )

    assert "Draft saved" not in response.content.decode()
    application.refresh_from_db()
    assert application.payload["data"] == before


def test_unverified_contact_cannot_reach_the_wizard(client, org_a):
    """The ticket's OTP step is discharged by A4: an application cannot be
    started, let alone submitted, until both contacts are verified. This asserts
    that gate really covers the wizard rather than assuming it does."""
    user = UserFactory()
    MembershipFactory(organisation=org_a, user=user)
    client.force_login(user)

    response = client.get(reverse("applications:step_product"))

    assert response.status_code == HTTP_FOUND
    assert response["Location"] == reverse("users:verify_contacts")
