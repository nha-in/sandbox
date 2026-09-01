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
from sandbox.applications.models import ApplicationState
from sandbox.applications.selectors import current_form_data
from sandbox.applications.services import create_draft
from sandbox.organisations.models import Product
from sandbox.organisations.tests.factories import MembershipFactory
from sandbox.organisations.tests.factories import ProductFactory
from sandbox.programmes.abdm import IntegrationIntent
from sandbox.programmes.abdm import RegistrationSolutionType
from sandbox.users.tests.factories import UserFactory
from sandbox.workflow import engine
from sandbox.workflow.engine import transition
from sandbox.workflow.services import record_review

pytestmark = pytest.mark.django_db

HTTP_OK = 200
HTTP_FOUND = 302
HTTP_NOT_FOUND = 404

DETAILS_POST = {
    "solution_types": [RegistrationSolutionType.EUA],
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


def _draft_with_details(product, applicant, data=None):
    """A draft whose registration form has been filled in, as the wizard leaves it."""
    application = create_draft(
        organisation=product.organisation,
        product=product,
        applicant=applicant,
        workflow_key="ABDM",
    )
    engine.submit_form(
        application=application,
        form_key="REGISTRATION",
        cleaned_data=dict(DETAILS_POST if data is None else data),
        user=applicant,
    )
    return application


def test_full_walk_without_javascript(member_client, org_a, org_member):
    """No htmx headers anywhere: every step is a real form post."""
    response = member_client.post(
        reverse("applications:step_product"),
        {"product": "", "product_name": "Care Bridge"},
    )
    assert response.status_code == HTTP_FOUND

    application = Application.objects.get(product__organisation=org_a)
    assert application.state == ApplicationState.DRAFT
    # a draft starts empty: the answers arrive at the details step
    assert not application.submissions.exists()
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
    registration = current_form_data(application, "REGISTRATION")
    assert registration["use_case_narrative"] == DETAILS_POST["use_case_narrative"]

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
        {"product": "", "product_name": "Care Bridge"},
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
    saved = current_form_data(application, "REGISTRATION")
    assert saved["use_case_narrative"] == partial["use_case_narrative"]

    # ...and it comes back pre-filled
    form = member_client.get(url).context["form"]
    assert form.initial["use_case_narrative"] == partial["use_case_narrative"]


def test_an_incomplete_draft_cannot_be_submitted(member_client, org_a, org_member):
    """Validation moved to SUBMIT, so it has to actually bite there."""
    member_client.post(
        reverse("applications:step_product"),
        {"product": "", "product_name": "Care Bridge"},
    )
    application = Application.objects.get(product__organisation=org_a)
    review_url = _org_url(
        "applications:step_review",
        org_a,
        external_id=application.external_id,
    )

    response = member_client.post(review_url, follow=True)

    assert response.status_code == HTTP_OK
    assert any(
        "complete the registration form" in str(m).lower()
        for m in response.context["messages"]
    )
    application.refresh_from_db()
    assert application.state == ApplicationState.DRAFT


def test_details_step_reports_payload_errors_as_form_errors(
    member_client,
    product_a,
    org_member,
):
    application = _draft_with_details(product_a, org_member)
    url = reverse(
        "applications:step_details",
        kwargs={"external_id": application.external_id},
    )
    response = member_client.post(url, {"use_case_narrative": ""})

    assert response.status_code == HTTP_OK
    assert response.context["form"].errors
    application.refresh_from_db()
    saved = current_form_data(application, "REGISTRATION")
    assert saved["use_case_narrative"] == DETAILS_POST["use_case_narrative"]


def test_the_index_lists_every_application_and_offers_another(
    member_client,
    product_a,
    org_member,
):
    """The integrator's home is a list, not a narration of one application.
    An organisation holds one per product, and the screen this replaced showed
    whichever was newest — a draft, the moment a second one is started."""
    application = _draft_with_details(product_a, org_member)
    response = member_client.get(
        _org_url("applications:index", product_a.organisation),
    )

    assert response.status_code == HTTP_OK
    listed = [
        entry["row"].application
        for group in response.context["groups"]
        for entry in group["rows"]
    ]
    assert listed == [application]
    body = response.content.decode()
    assert application.reference in body
    # One destination per row, and for a draft it is where the work is — the
    # row's own button says "Continue", so anywhere else would surprise.
    assert (
        reverse(
            "applications:step_details",
            kwargs={"external_id": application.external_id},
        )
        in body
    )
    assert reverse("applications:step_product") in body


# Going back from the details step


@pytest.fixture
def draft(product_a, org_member):
    """An unsubmitted application. The shared `application` fixture is SUBMITTED,
    and the product of a submitted application is deliberately fixed."""
    return _draft_with_details(product_a, org_member)


def _product_edit_url(application, organisation) -> str:
    return _org_url(
        "applications:step_product_edit",
        organisation,
        external_id=application.external_id,
    )


def test_going_back_shows_the_product_the_draft_already_holds(
    member_client,
    draft,
    org_a,
):
    """Its own live application is what makes a product unavailable, so without
    an exception for the draft being edited the picker came up empty."""
    response = member_client.get(_product_edit_url(draft, org_a))

    assert response.status_code == HTTP_OK
    form = response.context["form"]
    assert draft.product in form.products.values()
    assert form.initial["product"] == str(draft.product.pk)
    # the name box is the rename box, so it arrives holding the current name
    assert form.initial["product_name"] == draft.product.name


def test_going_back_and_continuing_does_not_open_a_second_application(
    member_client,
    draft,
    org_a,
):
    """The defect: `create_product` uniquifies a repeated name rather than
    refusing it, so Back-then-Continue used to leave a duplicate product and an
    abandoned draft behind, with nothing raised anywhere."""
    before = Application.objects.count()

    response = member_client.post(
        _product_edit_url(draft, org_a),
        {"product": str(draft.product.pk), "product_name": draft.product.name},
    )

    assert response.status_code == HTTP_FOUND
    assert Application.objects.count() == before
    assert Product.objects.filter(organisation=org_a).count() == 1


def test_going_back_can_repoint_the_draft_at_another_product(
    member_client,
    draft,
    org_a,
):
    other = ProductFactory(organisation=org_a)

    member_client.post(
        _product_edit_url(draft, org_a),
        {"product": str(other.pk), "product_name": ""},
    )

    draft.refresh_from_db()
    assert draft.product == other


def test_going_back_refuses_a_product_already_in_flight(
    member_client,
    draft,
    org_a,
    org_member,
):
    """UNIQUE (product, workflow_key) would refuse this at the database; the
    form says so instead of returning a 500."""
    taken = ProductFactory(organisation=org_a)
    create_draft(
        organisation=org_a,
        product=taken,
        applicant=org_member,
        workflow_key="ABDM",
    )

    response = member_client.post(
        _product_edit_url(draft, org_a),
        {"product": str(taken.pk), "product_name": ""},
    )

    assert response.status_code == HTTP_OK
    assert response.context["form"].errors
    draft.refresh_from_db()
    assert draft.product != taken


def test_editing_the_name_box_renames_the_product(member_client, draft, org_a):
    """The box arrives holding the current name; changing it is the rename."""
    response = member_client.post(
        _product_edit_url(draft, org_a),
        {"product": str(draft.product.pk), "product_name": "Care Bridge HMIS"},
    )

    assert response.status_code == HTTP_FOUND
    draft.refresh_from_db()
    assert draft.product.name == "Care Bridge HMIS"
    assert draft.product.slug == "care-bridge-hmis"
    assert Product.objects.filter(organisation=org_a).count() == 1


def test_switching_product_never_renames_the_one_you_switched_to(
    member_client,
    draft,
    org_a,
):
    """The bug this design exists to prevent. With scripting off the box keeps
    the old product's name when the dropdown moves; the form pins the rename to
    the product the box was rendered for, so the leftover is ignored."""
    other = ProductFactory(organisation=org_a, name="Untouched")
    original = draft.product.name

    member_client.post(
        _product_edit_url(draft, org_a),
        {"product": str(other.pk), "product_name": original},
    )

    other.refresh_from_db()
    draft.refresh_from_db()
    assert other.name == "Untouched"
    assert draft.product == other


def test_choosing_new_product_creates_one_and_leaves_the_old_alone(
    member_client,
    draft,
    org_a,
):
    original = draft.product

    member_client.post(
        _product_edit_url(draft, org_a),
        {"product": "new", "product_name": "Second Product"},
    )

    original.refresh_from_db()
    draft.refresh_from_db()
    assert original.name != "Second Product"
    assert draft.product.name == "Second Product"


def test_renaming_to_the_same_name_does_not_suffix_the_slug(
    member_client,
    draft,
    org_a,
):
    """The uniqueness scan has to skip the product being renamed, or saving a
    product under its own name walks into its own slug and appends `-2`."""
    member_client.post(
        _product_edit_url(draft, org_a),
        {"product": str(draft.product.pk), "product_name": draft.product.name},
    )

    slug = draft.product.slug
    draft.product.refresh_from_db()
    assert draft.product.slug == slug


def test_a_submitted_application_cannot_rename_its_product(
    member_client,
    draft,
    org_a,
    org_member,
):
    """A reviewer reading about "Care Bridge" must not have it renamed under
    them mid-review."""
    original = draft.product.name
    engine.transition(application=draft, action="SUBMIT", actor=org_member)

    member_client.post(
        _product_edit_url(draft, org_a),
        {"product": str(draft.product.pk), "product_name": "Something Else"},
    )

    draft.product.refresh_from_db()
    assert draft.product.name == original


def test_product_step_hides_products_with_a_live_application(
    member_client,
    application,
    org_a,
):
    """The one-live-application rule is enforced by the choices offered, so the
    partial-unique constraint can never surface as a 500."""
    free_product = ProductFactory(organisation=org_a)

    response = member_client.get(reverse("applications:step_product"))

    offered = set(response.context["form"].products.values())
    assert application.product not in offered
    assert free_product in offered


def test_product_step_drops_the_picker_when_nothing_is_selectable(
    member_client,
    application,
):
    """Filing for a second product when every product is already in flight: an
    empty dropdown asks nothing, so the form only offers a name."""
    response = member_client.get(reverse("applications:step_product"))

    form = response.context["form"]
    assert "product" not in form.fields
    assert form.fields["product_name"].required


def test_sent_back_application_is_editable_again(
    member_client,
    application,
    org_member,
    staff_user,
):
    record_review(
        application=application,
        reviewer=staff_user,
        decision="SEND_BACK",
        comment="Narrative is too thin.",
    )
    transition(
        application=application,
        action="SEND_BACK",
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
    """The engine always refused this write, but the save path ignored the
    refusal and flashed "Draft saved." over answers it had not touched."""
    url = _org_url(
        "applications:step_details",
        org_a,
        external_id=application.external_id,
    )
    before = current_form_data(application, "REGISTRATION")

    response = member_client.post(
        url,
        {**DETAILS_POST, "action": "save"},
        follow=True,
    )

    assert "Draft saved" not in response.content.decode()
    application.refresh_from_db()
    assert current_form_data(application, "REGISTRATION") == before


def test_a_provisioned_profile_is_editable_but_not_submittable(
    member_client,
    application,
    org_a,
    org_member,
):
    """Editing a live integration profile is a correction, not a resubmission.
    The review step used to offer "Submit for review" to anyone whose form was
    editable, and PROVISIONED is editable — so the button was there, and clicking
    it answered "SUBMIT is not legal from PROVISIONED"."""
    application.state = ApplicationState.PROVISIONED
    application.save(update_fields=["state"])

    details = _org_url(
        "applications:step_details",
        org_a,
        external_id=application.external_id,
    )
    response = member_client.get(details)
    assert response.status_code == HTTP_OK
    assert response.context["editable"]
    assert not response.context["can_submit"]

    # saving lands on the overview, not on a review step with nothing to review
    response = member_client.post(details, DETAILS_POST)
    assert response.status_code == HTTP_FOUND
    assert "/review/" not in response["Location"]

    review = _org_url(
        "applications:step_review",
        org_a,
        external_id=application.external_id,
    )
    assert "Submit for review" not in member_client.get(review).content.decode()

    application.refresh_from_db()
    assert application.state == ApplicationState.PROVISIONED


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


def test_the_name_box_and_dropdown_are_paired_for_the_enhancement(
    member_client,
    draft,
    org_a,
):
    """`project.js` copies the selected option's label into the box so the
    screen cannot disagree with the selection. It finds them by these hooks."""
    body = member_client.get(_product_edit_url(draft, org_a)).content.decode()

    assert "data-product-select" in body
    assert 'data-product-new="new"' in body
    assert "data-product-name" in body
