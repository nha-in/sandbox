"""The console's exit half (C8).

The sandbox review and the exit review are the same screen driven by different
rows in the state table, so what is asserted here is mostly that the exit half
reaches the places the sandbox half already does: the reviewer sees the bundle
they are deciding on, a rejection can say why, and the buttons offered are the
ones the engine would accept.

The reason for the "can say why" tests: `transition()` refuses a comment on a
review-driven action, and `record_review()` used to refuse any application that
was not SUBMITTED. Between them an exit rejection had nowhere to record a
reason, while every test stayed green.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from sandbox.applications.models import ApplicationState
from sandbox.catalog.tests.factories import MilestoneFactory
from sandbox.declarations import services
from sandbox.declarations.models import DeclarationState
from sandbox.declarations.tests.conftest import upload
from sandbox.workflow.machine import Action
from sandbox.workflow.models import ReviewDecision
from sandbox.workflow.models import WorkflowReview
from sandbox.workflow.selectors import current_round

pytestmark = pytest.mark.django_db

HTTP_OK = 200
HTTP_FOUND = 302
ROUND_TWO = 2


@pytest.fixture
def milestone(db):
    return MilestoneFactory.create(key="m1")


@pytest.fixture
def exit_requested(mock_s3, application, milestone, member):
    """An application that has asked to go to production, bundle and all."""
    services.submit_milestone_declaration(
        application=application,
        milestone=milestone,
        actor=member,
    )
    services.submit_exit_declaration(
        application=application,
        milestones=[milestone],
        payload={"summary": "Two HIPs live."},
        files=[upload()],
        actor=member,
    )
    application.state = ApplicationState.EXIT_REQUESTED
    application.save(update_fields=["state"])
    return application


def detail_url(application):
    return reverse(
        "console:application_detail",
        kwargs={"external_id": application.external_id},
    )


def decide_url(application):
    return reverse(
        "console:decide",
        kwargs={"external_id": application.external_id},
    )


def _to_review(client, application):
    client.post(decide_url(application), {"action": Action.START_EXIT_REVIEW})
    application.refresh_from_db()
    return application


# What the reviewer is shown


def test_the_reviewer_sees_the_bundle_they_are_deciding_on(
    admin_client_,
    exit_requested,
    milestone,
):
    response = admin_client_.get(detail_url(exit_requested))

    bundle = response.context["exit_bundle"]
    assert bundle["milestones"] == [milestone]
    assert bundle["summary"] == "Two HIPs live."
    assert len(bundle["documents"]) == 1


def test_an_application_with_no_pending_exit_shows_no_panel(
    admin_client_,
    application,
):
    response = admin_client_.get(detail_url(application))

    assert response.context["exit_bundle"] is None


def test_the_evidence_is_linked_from_the_page_that_names_it(
    admin_client_,
    exit_requested,
):
    """A filename rendered with no working link is worse than no panel."""
    document = exit_requested.declarations.get(kind="EXIT").documents.get()
    body = admin_client_.get(detail_url(exit_requested)).content.decode()

    assert (
        reverse(
            "console:document_download",
            kwargs={"external_id": document.external_id},
        )
        in body
    )


# Buttons match the engine


def test_exit_requested_offers_only_the_move_into_review(
    admin_client_,
    exit_requested,
):
    response = admin_client_.get(detail_url(exit_requested))

    offered = {row["value"] for row in response.context["decision_actions"]}
    assert offered == {Action.START_EXIT_REVIEW}


def test_exit_review_offers_the_three_outcomes(admin_client_, exit_requested):
    _to_review(admin_client_, exit_requested)

    response = admin_client_.get(detail_url(exit_requested))

    offered = {row["value"] for row in response.context["decision_actions"]}
    assert offered == {
        Action.APPROVE_EXIT,
        Action.REJECT_EXIT,
        Action.SEND_BACK_EXIT,
    }


# Deciding


def test_approving_an_exit_settles_the_declaration(admin_client_, exit_requested):
    _to_review(admin_client_, exit_requested)

    admin_client_.post(
        decide_url(exit_requested),
        {"action": Action.APPROVE_EXIT, "comment": "Evidence is complete."},
    )

    exit_requested.refresh_from_db()
    assert exit_requested.state == ApplicationState.PRODUCTION_APPROVED
    declaration = exit_requested.declarations.get(kind="EXIT")
    assert declaration.state == DeclarationState.APPROVED


def test_a_rejection_records_its_reason_on_the_review_row(
    admin_client_,
    exit_requested,
):
    """`workflow_review.comment` is the single home for the text (03-database),
    and it has to be reachable in EXIT_REVIEW or a rejection is unexplained."""
    _to_review(admin_client_, exit_requested)

    admin_client_.post(
        decide_url(exit_requested),
        {"action": Action.REJECT_EXIT, "comment": "The consent logs are missing."},
    )

    exit_requested.refresh_from_db()
    assert exit_requested.state == ApplicationState.EXIT_REJECTED
    review = WorkflowReview.objects.get(application=exit_requested)
    assert review.decision == ReviewDecision.REJECT
    assert review.comment == "The consent logs are missing."


def test_a_rejection_without_a_reason_is_refused(admin_client_, exit_requested):
    _to_review(admin_client_, exit_requested)

    admin_client_.post(decide_url(exit_requested), {"action": Action.REJECT_EXIT})

    exit_requested.refresh_from_db()
    assert exit_requested.state == ApplicationState.EXIT_REVIEW
    assert not WorkflowReview.objects.exists()


def test_a_second_exit_review_opens_a_new_round(admin_client_, exit_requested):
    """Without this the second reviewer's row would overwrite the first: the
    unique index is (application, reviewer, round), and a round that never
    advances makes the two collide."""
    _to_review(admin_client_, exit_requested)
    admin_client_.post(
        decide_url(exit_requested),
        {"action": Action.REJECT_EXIT, "comment": "Round one: logs missing."},
    )
    exit_requested.refresh_from_db()

    assert current_round(exit_requested) == ROUND_TWO


def test_starting_the_review_puts_its_note_on_the_transition(
    admin_client_,
    exit_requested,
):
    """START_EXIT_REVIEW expresses no opinion, so it has no review row to sit
    on — the transition's own comment column is the other home the schema
    allows, and it must not be silently dropped."""
    admin_client_.post(
        decide_url(exit_requested),
        {"action": Action.START_EXIT_REVIEW, "comment": "Picked this up."},
    )

    transition = exit_requested.transitions.get(action=Action.START_EXIT_REVIEW)
    assert transition.comment == "Picked this up."
    assert not WorkflowReview.objects.exists()
