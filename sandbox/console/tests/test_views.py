"""Console behaviour: what each actor may do, and that buttons match the engine."""

from __future__ import annotations

import pytest
from django.urls import reverse

from sandbox.applications.models import ApplicationState
from sandbox.applications.tests.factories import ApplicationFactory
from sandbox.organisations.tests.factories import MembershipFactory
from sandbox.workflow.machine import Action
from sandbox.workflow.models import ReviewDecision
from sandbox.workflow.models import WorkflowReview
from sandbox.workflow.models import WorkflowTransition

pytestmark = pytest.mark.django_db

HTTP_OK = 200
HTTP_FORBIDDEN = 403


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


# Buttons match the engine


def test_reviewer_can_opine_but_moves_nothing(reviewer_client, submitted):
    """`review_application` records opinions; transitions need their own."""
    response = reviewer_client.get(detail_url(submitted))

    assert response.context["decision_actions"] == []
    assert response.context["can_review"] is True


def test_admin_sees_the_decision_buttons(admin_client_, submitted):
    response = admin_client_.get(detail_url(submitted))

    offered = {row["value"] for row in response.context["decision_actions"]}
    assert offered == {Action.APPROVE, Action.REJECT, Action.SEND_BACK}


def test_draft_offers_no_decisions(admin_client_):
    draft = ApplicationFactory.create(state=ApplicationState.DRAFT)

    response = admin_client_.get(detail_url(draft))

    assert response.context["decision_actions"] == []


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
    assert "not legal" in response.content.decode()


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


def test_payload_is_rendered_as_labels_not_json(reviewer_client, submitted):
    body = reviewer_client.get(detail_url(submitted)).content.decode()

    assert "schema_version" not in body
    assert "Solution types" in body


def test_state_badges_show_their_own_count(reviewer_client, submitted):
    """Regression: the template rendered the whole counts dict on every badge."""
    ApplicationFactory.create(state=ApplicationState.DRAFT)

    response = reviewer_client.get(reverse("console:queue"))
    filters = {f["value"]: f["count"] for f in response.context["state_filters"]}

    assert filters[ApplicationState.SUBMITTED] == 1
    assert filters[ApplicationState.DRAFT] == 1
    assert filters[ApplicationState.REJECTED] == 0
    assert "'DRAFT':" not in response.content.decode()


def test_empty_states_get_no_badge_but_stay_in_the_dropdown(reviewer_client, submitted):
    body = reviewer_client.get(reverse("console:queue")).content.decode()

    assert "?state=WITHDRAWN" not in body  # no badge for a state with nothing in it
    assert 'value="WITHDRAWN"' in body  # but still filterable from the dropdown


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
