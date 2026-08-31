"""Reviews are advisory opinions, an approve guard, and rounds."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Permission

from sandbox.applications.models import ApplicationState
from sandbox.applications.tests.factories import ApplicationFactory
from sandbox.audit.models import AuditEvent
from sandbox.organisations.tests.factories import MembershipFactory
from sandbox.users.models import User
from sandbox.users.tests.factories import UserFactory
from sandbox.utils.errors import DomainError
from sandbox.workflow import engine as workflow_engine
from sandbox.workflow.engine import transition
from sandbox.workflow.models import ReviewDecision
from sandbox.workflow.models import WorkflowReview
from sandbox.workflow.selectors import current_round
from sandbox.workflow.selectors import decidable_actions
from sandbox.workflow.selectors import history_for
from sandbox.workflow.selectors import queue_by_state
from sandbox.workflow.selectors import review_tally
from sandbox.workflow.selectors import reviews_for_round
from sandbox.workflow.services import record_review

pytestmark = pytest.mark.django_db

ROUND_TWO = 2
TWO_REVIEWS = 2


def grant(user: User, *codenames: str) -> User:
    for codename in codenames:
        user.user_permissions.add(Permission.objects.get(codename=codename))
    # a fresh instance: the permission cache is per-instance and already warm
    return User.objects.get(pk=user.pk)


@pytest.fixture(autouse=True)
def _no_hooks():
    workflow_engine.clear_hooks()
    yield
    workflow_engine.clear_hooks()


@pytest.fixture
def owner_and_application():
    application = ApplicationFactory.create()
    owner = UserFactory.create()
    MembershipFactory.create(organisation=application.product.organisation, user=owner)
    return owner, application


@pytest.fixture
def submitted(owner_and_application):
    owner, application = owner_and_application
    transition(application=application, action="SUBMIT", actor=owner)
    application.refresh_from_db()
    return application


@pytest.fixture
def reviewer():
    return grant(UserFactory.create(is_staff=True), "review_application")


@pytest.fixture
def admin():
    return grant(
        UserFactory.create(is_staff=True),
        "review_application",
        "approve_application",
        "reject_application",
        "send_back_application",
    )


# Authority


def test_reviewer_can_record_an_opinion(submitted, reviewer):
    review = record_review(
        application=submitted,
        reviewer=reviewer,
        decision=ReviewDecision.APPROVE,
        comment="ABHA flows look correct.",
    )

    assert review.decision == ReviewDecision.APPROVE
    assert review.round == 1
    assert review.comment == "ABHA flows look correct."


def test_recording_a_review_requires_the_review_permission(submitted):
    nobody = UserFactory.create(is_staff=True)

    with pytest.raises(DomainError) as excinfo:
        record_review(
            application=submitted,
            reviewer=nobody,
            decision=ReviewDecision.APPROVE,
        )

    assert excinfo.value.code == "forbidden"


def test_a_reviewer_cannot_approve_the_application(submitted, reviewer):
    """The review permission is an opinion, not authority to decide."""
    record_review(
        application=submitted,
        reviewer=reviewer,
        decision=ReviewDecision.APPROVE,
    )

    with pytest.raises(DomainError) as excinfo:
        transition(application=submitted, action="APPROVE", actor=reviewer)

    assert excinfo.value.code == "forbidden"


def test_admin_can_approve_with_zero_reviews_recorded(submitted, admin):
    """Deliberate parity with legacy: no quorum, the admin's call stands alone."""
    assert not WorkflowReview.objects.filter(application=submitted).exists()

    transition(application=submitted, action="APPROVE", actor=admin)

    submitted.refresh_from_db()
    assert submitted.state == ApplicationState.SANDBOX_APPROVED


def test_reviews_do_not_gate_approval_even_when_they_disagree(
    submitted,
    reviewer,
    admin,
):
    record_review(
        application=submitted,
        reviewer=reviewer,
        decision=ReviewDecision.REJECT,
        comment="Not convinced.",
    )

    transition(application=submitted, action="APPROVE", actor=admin)

    submitted.refresh_from_db()
    assert submitted.state == ApplicationState.SANDBOX_APPROVED


# State


def test_cannot_review_an_application_that_is_not_submitted(
    owner_and_application,
    reviewer,
):
    _owner, application = owner_and_application

    with pytest.raises(DomainError) as excinfo:
        record_review(
            application=application,
            reviewer=reviewer,
            decision=ReviewDecision.APPROVE,
        )

    assert excinfo.value.code == "illegal_review"


def test_an_unknown_decision_is_refused(submitted, reviewer):
    with pytest.raises(DomainError) as excinfo:
        record_review(application=submitted, reviewer=reviewer, decision="MAYBE")

    assert excinfo.value.code == "invalid"


# Rounds


def test_re_reviewing_in_the_same_round_updates_the_row(submitted, reviewer):
    record_review(
        application=submitted,
        reviewer=reviewer,
        decision=ReviewDecision.SEND_BACK,
        comment="Missing the HIU narrative.",
    )
    record_review(
        application=submitted,
        reviewer=reviewer,
        decision=ReviewDecision.APPROVE,
        comment="Narrative supplied out of band.",
    )

    rows = WorkflowReview.objects.filter(application=submitted)
    assert len(rows) == 1
    assert rows[0].decision == ReviewDecision.APPROVE


def test_send_back_and_resubmit_opens_a_new_round(
    submitted,
    owner_and_application,
    reviewer,
    admin,
):
    owner, _ = owner_and_application
    assert current_round(submitted) == 1

    record_review(
        application=submitted,
        reviewer=reviewer,
        decision=ReviewDecision.SEND_BACK,
        comment="Round one: fix the payer categories.",
    )
    transition(application=submitted, action="SEND_BACK", actor=admin)
    transition(application=submitted, action="SUBMIT", actor=owner)
    submitted.refresh_from_db()

    assert current_round(submitted) == ROUND_TWO

    record_review(
        application=submitted,
        reviewer=reviewer,
        decision=ReviewDecision.APPROVE,
        comment="Round two: fixed.",
    )

    assert WorkflowReview.objects.filter(application=submitted).count() == TWO_REVIEWS


def test_the_previous_round_stays_readable(
    submitted,
    owner_and_application,
    reviewer,
    admin,
):
    owner, _ = owner_and_application
    record_review(
        application=submitted,
        reviewer=reviewer,
        decision=ReviewDecision.SEND_BACK,
        comment="Round one comment.",
    )
    transition(application=submitted, action="SEND_BACK", actor=admin)
    transition(application=submitted, action="SUBMIT", actor=owner)
    submitted.refresh_from_db()
    record_review(
        application=submitted,
        reviewer=reviewer,
        decision=ReviewDecision.APPROVE,
        comment="Round two comment.",
    )

    first = reviews_for_round(submitted, 1)
    assert len(first) == 1
    assert first[0].comment == "Round one comment."
    assert not first[0].deleted  # readable, not soft-deleted


def test_two_reviewers_may_both_record_in_one_round(submitted, reviewer):
    second = grant(UserFactory.create(is_staff=True), "review_application")

    record_review(
        application=submitted,
        reviewer=reviewer,
        decision=ReviewDecision.APPROVE,
    )
    record_review(
        application=submitted,
        reviewer=second,
        decision=ReviewDecision.REJECT,
    )

    assert reviews_for_round(submitted).count() == TWO_REVIEWS


# Tally


def test_tally_counts_the_current_round_only(
    submitted,
    owner_and_application,
    reviewer,
    admin,
):
    owner, _ = owner_and_application
    record_review(
        application=submitted,
        reviewer=reviewer,
        decision=ReviewDecision.SEND_BACK,
    )
    transition(application=submitted, action="SEND_BACK", actor=admin)
    transition(application=submitted, action="SUBMIT", actor=owner)
    submitted.refresh_from_db()
    record_review(
        application=submitted,
        reviewer=reviewer,
        decision=ReviewDecision.APPROVE,
    )

    assert review_tally(submitted) == {"APPROVE": 1, "REJECT": 0, "SEND_BACK": 0}
    assert review_tally(submitted, 1) == {"APPROVE": 0, "REJECT": 0, "SEND_BACK": 1}


def test_tally_is_zeroed_when_nobody_has_reviewed(submitted):
    assert review_tally(submitted) == {"APPROVE": 0, "REJECT": 0, "SEND_BACK": 0}


# Comments stay single-homed


def test_the_review_comment_is_not_copied_onto_the_transition(
    submitted,
    reviewer,
    admin,
):
    record_review(
        application=submitted,
        reviewer=reviewer,
        decision=ReviewDecision.APPROVE,
        comment="the only home for this text",
    )

    record = transition(application=submitted, action="APPROVE", actor=admin)

    assert record.comment == ""


# Audit


def test_recording_a_review_is_audited(submitted, reviewer):
    record_review(
        application=submitted,
        reviewer=reviewer,
        decision=ReviewDecision.APPROVE,
        comment="fine",
    )

    event = AuditEvent.objects.get(action="application.reviewed")
    assert event.actor == reviewer
    assert event.data["decision"] == ReviewDecision.APPROVE
    assert event.data["round"] == 1
    assert "fine" not in str(event.data)  # the comment lives on the review row


# Console-facing selectors


def test_available_actions_offers_only_what_the_actor_may_do(
    submitted,
    reviewer,
    admin,
):
    """A screen must not offer a move `transition()` would then refuse."""
    assert set(decidable_actions(submitted, admin)) >= {"APPROVE", "REJECT"}
    # review_application is opinion-only: a reviewer may move nothing at all
    assert decidable_actions(submitted, reviewer) == ()


def test_available_actions_hides_system_moves(submitted, admin):
    assert "START_PROVISIONING" not in decidable_actions(submitted, admin)


def test_available_actions_is_empty_for_anonymous(submitted):
    assert decidable_actions(submitted, None) == ()


def test_owner_moves_are_offered_only_to_members(
    submitted,
    owner_and_application,
    admin,
):
    owner, _ = owner_and_application

    assert "WITHDRAW" in decidable_actions(submitted, owner)
    assert "WITHDRAW" not in decidable_actions(submitted, admin)


def test_history_is_newest_first(submitted, admin):
    transition(application=submitted, action="SEND_BACK", actor=admin)

    actions = [row.action for row in history_for(submitted)]

    assert actions == ["SEND_BACK", "SUBMIT"]


def test_queue_by_state_finds_submitted_applications(submitted):
    assert submitted in queue_by_state(ApplicationState.SUBMITTED)
    assert submitted not in queue_by_state(ApplicationState.DRAFT)
