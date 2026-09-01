"""Console behaviour: what each actor may do, and that choices match the engine."""

from __future__ import annotations

import re

import pytest
from django.urls import reverse

from sandbox.applications.models import ApplicationState
from sandbox.applications.tests.factories import ApplicationFactory
from sandbox.console.tests.conftest import grant
from sandbox.console.tests.conftest import signed_in
from sandbox.organisations.tests.factories import MembershipFactory
from sandbox.users.tests.factories import UserFactory
from sandbox.workflow.models import ReviewDecision
from sandbox.workflow.models import WorkflowReview
from sandbox.workflow.models import WorkflowTransition

pytestmark = pytest.mark.django_db

HTTP_OK = 200
HTTP_FORBIDDEN = 403
HTTP_NOT_FOUND = 404


@pytest.fixture
def submitted():
    application = ApplicationFactory.create(state=ApplicationState.SUBMITTED)
    MembershipFactory.create(
        organisation=application.product.organisation,
        user=application.applicant,
    )
    return application


def detail_url(application):
    return reverse(
        "console:application_detail",
        kwargs={"external_id": application.external_id},
    )


# Queue


def test_queue_lists_applications(reviewer_client, submitted):
    response = reviewer_client.get(reverse("console:queue"))

    assert response.status_code == HTTP_OK
    assert submitted.reference in response.content.decode()


def test_queue_filters_by_state(reviewer_client, submitted):
    draft = ApplicationFactory.create(state=ApplicationState.DRAFT)

    body = reviewer_client.get(
        reverse("console:queue"),
        {"state": ApplicationState.SUBMITTED},
    ).content.decode()

    assert submitted.reference in body
    assert draft.reference not in body


def test_queue_search_matches_reference(reviewer_client, submitted):
    other = ApplicationFactory.create(state=ApplicationState.SUBMITTED)

    body = reviewer_client.get(
        reverse("console:queue"),
        {"q": submitted.reference},
    ).content.decode()

    assert submitted.reference in body
    assert other.reference not in body


def test_searching_inside_a_state_stays_inside_it(reviewer_client, submitted):
    """The tabs own the state and the box owns the text. The box has to carry
    the state or searching silently widens the queue back to everything."""
    organisation = submitted.product.organisation
    draft = ApplicationFactory.create(
        state=ApplicationState.DRAFT,
        product__organisation=organisation,
    )

    body = reviewer_client.get(
        reverse("console:queue"),
        {"state": ApplicationState.SUBMITTED, "q": organisation.name},
    ).content.decode()

    assert submitted.reference in body
    assert draft.reference not in body


def test_the_selected_state_keeps_its_tab_when_it_matches_nothing(
    reviewer_client,
    submitted,
):
    """A tab hidden because its count is zero cannot be left highlighted with
    no way back — you would be filtered into a state you cannot unselect."""
    body = reviewer_client.get(
        reverse("console:queue"),
        {"state": ApplicationState.WITHDRAWN},
    ).content.decode()

    assert "?state=WITHDRAWN" in body


# Choices match the engine


def test_reviewer_can_opine_but_moves_nothing(reviewer_client, submitted):
    """`review_abdm` records opinions; transitions need their own."""
    response = reviewer_client.get(detail_url(submitted))

    assert response.context["decision_choices"] == []
    assert response.context["can_review"] is True


def test_admin_sees_the_decisions_on_offer(admin_client_, submitted):
    response = admin_client_.get(detail_url(submitted))

    offered = {row["value"] for row in response.context["decision_choices"]}
    assert offered == {"APPROVE", "REJECT", "SEND_BACK"}


def test_whoever_decides_gets_one_comment_box_not_two(admin_client_, submitted):
    """Deciding records the comment as the decider's review, so a separate
    "record a review" panel beside it was a second door to the same table."""
    review_url = reverse(
        "console:record_review",
        kwargs={"external_id": submitted.external_id},
    )

    body = admin_client_.get(detail_url(submitted)).content.decode()

    assert body.count('name="comment"') == 1
    assert review_url not in body


def test_a_sandbox_decision_carries_no_extra_fields(admin_client_, submitted):
    """Only the exit's APPROVE writes a decision form; the sandbox review has
    nothing to reveal, so the card is the dropdown and a comment."""
    response = admin_client_.get(detail_url(submitted))

    assert response.context["approval_fields"] is False
    assert 'id="approve-fields"' not in response.content.decode()


def test_send_back_is_not_dressed_as_a_rejection(admin_client_, submitted):
    """Nothing is lost when work goes back, so it is not destructive — but the
    plain forward style would read as approval."""
    response = admin_client_.get(detail_url(submitted))

    variants = {
        row["value"]: row["variant"] for row in response.context["decision_choices"]
    }
    assert variants == {
        "APPROVE": "default",
        "SEND_BACK": "warning",
        "REJECT": "destructive",
    }


def test_the_decisions_read_as_words(admin_client_, submitted):
    """`value="SEND_BACK"` is the wire; the label is what a person reads."""
    body = admin_client_.get(detail_url(submitted)).content.decode()

    assert re.search(r">\s*Send back\s*<", body)
    assert not re.search(r">\s*SEND_BACK\s*<", body)


def test_draft_offers_no_decisions(admin_client_):
    draft = ApplicationFactory.create(state=ApplicationState.DRAFT)

    response = admin_client_.get(detail_url(draft))

    assert response.context["decision_choices"] == []


# Actions


def test_admin_can_approve(admin_client_, submitted):
    admin_client_.post(
        reverse("console:decide", kwargs={"external_id": submitted.external_id}),
        {"action": "APPROVE"},
    )

    submitted.refresh_from_db()
    assert submitted.state == ApplicationState.SANDBOX_APPROVED
    assert WorkflowTransition.objects.filter(application=submitted).count() == 1


def test_a_decision_comment_lands_on_the_review_row(admin_client_, submitted):
    """A5 refuses a comment on a review-driven transition, so it goes here."""
    admin_client_.post(
        reverse("console:decide", kwargs={"external_id": submitted.external_id}),
        {"action": "REJECT", "comment": "Payer flow is not evidenced."},
    )

    submitted.refresh_from_db()
    assert submitted.state == ApplicationState.REJECTED
    review = WorkflowReview.objects.get(application=submitted)
    assert review.comment == "Payer flow is not evidenced."
    assert WorkflowTransition.objects.get(application=submitted).comment == ""


def test_reject_without_a_comment_is_refused(admin_client_, submitted):
    response = admin_client_.post(
        reverse("console:decide", kwargs={"external_id": submitted.external_id}),
        {"action": "REJECT"},
        follow=True,
    )

    submitted.refresh_from_db()
    assert submitted.state == ApplicationState.SUBMITTED
    assert "Say why" in response.content.decode()


def test_a_forced_illegal_action_is_refused_server_side(admin_client_):
    """The button is hidden; the guard is what actually stops it."""
    draft = ApplicationFactory.create(state=ApplicationState.DRAFT)

    response = admin_client_.post(
        reverse("console:decide", kwargs={"external_id": draft.external_id}),
        {"action": "APPROVE"},
        follow=True,
    )

    draft.refresh_from_db()
    assert draft.state == ApplicationState.DRAFT
    assert "not available" in response.content.decode()


def test_a_reviewer_forcing_approve_is_refused(reviewer_client, submitted):
    response = reviewer_client.post(
        reverse("console:decide", kwargs={"external_id": submitted.external_id}),
        {"action": "APPROVE"},
        follow=True,
    )

    submitted.refresh_from_db()
    assert submitted.state == ApplicationState.SUBMITTED
    assert "requires" in response.content.decode()


def test_reviewer_can_record_a_review(reviewer_client, submitted):
    reviewer_client.post(
        reverse("console:record_review", kwargs={"external_id": submitted.external_id}),
        {"decision": ReviewDecision.APPROVE, "comment": "Looks right."},
    )

    review = WorkflowReview.objects.get(application=submitted)
    assert review.decision == ReviewDecision.APPROVE
    assert review.comment == "Looks right."


def test_the_tally_is_rendered(admin_client_, reviewer_client, submitted):
    reviewer_client.post(
        reverse("console:record_review", kwargs={"external_id": submitted.external_id}),
        {"decision": ReviewDecision.SEND_BACK, "comment": "Needs the payer flow."},
    )

    body = admin_client_.get(detail_url(submitted)).content.decode()

    assert "SEND_BACK: 1" in body
    assert "Needs the payer flow." in body


def test_admin_can_approve_with_zero_reviews(admin_client_, submitted):
    assert not WorkflowReview.objects.filter(application=submitted).exists()

    admin_client_.post(
        reverse("console:decide", kwargs={"external_id": submitted.external_id}),
        {"action": "APPROVE"},
    )

    submitted.refresh_from_db()
    assert submitted.state == ApplicationState.SANDBOX_APPROVED


def test_staff_on_no_team_see_nothing(enable_mfa, submitted):
    """`is_staff` opens the console door; a role is what puts anything behind
    it. Someone with no role gets an empty queue, not the whole pipeline."""
    newcomer = UserFactory.create(is_staff=True)
    client = signed_in(enable_mfa(newcomer))

    queue_page = client.get(reverse("console:queue"))
    detail = client.get(detail_url(submitted))

    assert queue_page.status_code == HTTP_OK
    assert list(queue_page.context["applications"]) == []
    assert queue_page.context["nav_counts"]["queue"] == 0
    assert detail.status_code == HTTP_NOT_FOUND


def test_a_team_cannot_see_another_programmes_applications(enable_mfa, submitted):
    """Permissions are per programme because different teams review different
    programmes — and a team with no authority over an application has no
    business reading its evidence either. Not found, not forbidden."""
    outsider = grant(UserFactory.create(is_staff=True), "review_abdm")
    client = signed_in(enable_mfa(outsider))

    queue_body = client.get(reverse("console:queue")).content.decode()
    detail = client.get(detail_url(submitted))

    assert submitted.reference not in queue_body
    assert detail.status_code == HTTP_NOT_FOUND


def test_payload_is_rendered_as_labels_not_json(reviewer_client, submitted):
    body = reviewer_client.get(detail_url(submitted)).content.decode()

    assert "schema_version" not in body
    # headings come from the form the applicant filled in...
    assert "Solution type" in body
    # ...and codes are resolved: `ABHA_M1` is not an answer a reviewer can read
    assert "ABHA Creation/Verification - M1" in body
    assert "ABHA_M1" not in body


def test_state_badges_show_their_own_count(reviewer_client, submitted):
    """Regression: the template rendered the whole counts dict on every badge."""
    ApplicationFactory.create(state=ApplicationState.DRAFT)

    response = reviewer_client.get(reverse("console:queue"))
    filters = {f["value"]: f["count"] for f in response.context["state_filters"]}

    assert filters[ApplicationState.SUBMITTED] == 1
    assert filters[ApplicationState.DRAFT] == 1
    assert filters[ApplicationState.REJECTED] == 0
    assert "'DRAFT':" not in response.content.decode()


def test_a_state_with_nothing_in_it_gets_no_tab(reviewer_client, submitted):
    """The tabs are the whole state filter now, so an empty one is simply not
    offered rather than hidden from one control and present in another."""
    body = reviewer_client.get(reverse("console:queue")).content.decode()

    assert "?state=WITHDRAWN" not in body


def test_state_badges_count_only_what_the_search_shows(reviewer_client, submitted):
    """A badge reading "Draft 1" beside a filtered table with no drafts sends a
    reviewer hunting for a row that is not there."""
    ApplicationFactory.create(state=ApplicationState.DRAFT)

    response = reviewer_client.get(
        reverse("console:queue"),
        {"q": submitted.reference},
    )

    counts = {row["value"]: row["count"] for row in response.context["state_filters"]}
    assert counts[ApplicationState.SUBMITTED] == 1
    assert counts[ApplicationState.DRAFT] == 0
