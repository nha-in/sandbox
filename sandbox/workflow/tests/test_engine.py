"""The engine's two write paths.

`submit_form` and `transition` are the only code that writes submissions and
state, so their refusals are the design's enforcement points: editability,
membership, dependency order, the STAFF door, rounds and decision atomicity.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import timedelta

import pytest
from django.contrib.auth.models import Permission
from django.utils import timezone

from sandbox.applications.models import ApplicationDocument
from sandbox.applications.models import ApplicationFormSubmission
from sandbox.applications.tests.factories import ApplicationFactory
from sandbox.organisations.tests.factories import MembershipFactory
from sandbox.programmes.abdm import ABDMExitWorkflow
from sandbox.programmes.abdm import DocumentKind
from sandbox.programmes.abdm import Milestone
from sandbox.programmes.abdm import SolutionType
from sandbox.programmes.abdm import milestone_form_key
from sandbox.users.tests.factories import UserFactory
from sandbox.utils.errors import DomainError
from sandbox.workflow import engine

pytestmark = pytest.mark.django_db

#: the second of anything: a superseded revision, or the round after a rebuff
SECOND = 2


@pytest.fixture
def application():
    # unregistered: these tests are about the engine filling the form in
    return ApplicationFactory.create(
        workflow_key="ABDM",
        state="DRAFT",
        registered=False,
    )


@pytest.fixture
def owner(application):
    user = UserFactory.create()
    MembershipFactory.create(
        organisation=application.product.organisation,
        user=user,
    )
    return user


@pytest.fixture
def outsider():
    return UserFactory.create()


def _registration_data():
    return {"solution_types": [SolutionType.HMIS.value]}


# ---------------------------------------------------------------------------
# submit_form


def test_submit_form_writes_a_current_revision(application, owner):
    submission = engine.submit_form(
        application=application,
        form_key="REGISTRATION",
        cleaned_data=_registration_data(),
        user=owner,
    )
    assert submission.is_current
    assert submission.round == application.round
    assert submission.submitted_by == owner


def test_resubmission_supersedes_and_leaves_one_current(application, owner):
    first = engine.submit_form(
        application=application,
        form_key="REGISTRATION",
        cleaned_data=_registration_data(),
        user=owner,
    )
    second = engine.submit_form(
        application=application,
        form_key="REGISTRATION",
        cleaned_data={"solution_types": [SolutionType.LMIS.value]},
        user=owner,
    )
    first.refresh_from_db()
    assert not first.is_current
    assert second.is_current
    current = ApplicationFormSubmission.objects.filter(
        application=application,
        form_key="REGISTRATION",
        is_current=True,
    )
    assert current.count() == 1
    # the superseded revision is still the record of what was claimed
    assert first.data["solution_types"] == [SolutionType.HMIS.value]


def test_submit_form_refuses_a_state_outside_editable_states(application, owner):
    application.state = "SUBMITTED"
    application.save(update_fields=["state"])
    with pytest.raises(DomainError, match="not editable"):
        engine.submit_form(
            application=application,
            form_key="REGISTRATION",
            cleaned_data=_registration_data(),
            user=owner,
        )


def test_submit_form_refuses_a_non_member(application, outsider):
    with pytest.raises(DomainError, match="not a member"):
        engine.submit_form(
            application=application,
            form_key="REGISTRATION",
            cleaned_data=_registration_data(),
            user=outsider,
        )


def test_submit_form_refuses_a_locked_milestone(application, owner):
    application.state = "PROVISIONED"
    application.save(update_fields=["state"])
    with pytest.raises(DomainError, match="requires"):
        engine.submit_form(
            application=application,
            form_key=milestone_form_key(Milestone.HEALTH_LOCKER),
            cleaned_data={},
            user=owner,
        )


def test_submit_form_allows_a_milestone_once_its_prerequisite_is_current(
    application,
    owner,
):
    application.state = "PROVISIONED"
    application.save(update_fields=["state"])
    engine.submit_form(
        application=application,
        form_key=milestone_form_key(Milestone.PHR),
        cleaned_data={},
        user=owner,
    )
    submission = engine.submit_form(
        application=application,
        form_key=milestone_form_key(Milestone.HEALTH_LOCKER),
        cleaned_data={},
        user=owner,
    )
    assert submission.is_current


def test_submit_form_refuses_a_staff_form(application, owner):
    exit_application = ApplicationFactory.create(
        workflow_key="ABDM_EXIT",
        state="DRAFT",
        product=application.product,
        registered=False,
    )
    with pytest.raises(DomainError, match="written by the engine"):
        engine.submit_form(
            application=exit_application,
            form_key="EXIT_DECISION",
            cleaned_data={"approved_solution_types": []},
            user=owner,
        )


def test_a_repeatable_form_never_sets_is_current(application, owner):
    application.state = "PROVISIONED"
    application.save(update_fields=["state"])
    first = engine.submit_form(
        application=application,
        form_key="DHIS_CLAIM",
        cleaned_data={"solution_type": SolutionType.HMIS.value},
        user=owner,
    )
    second = engine.submit_form(
        application=application,
        form_key="DHIS_CLAIM",
        cleaned_data={"solution_type": SolutionType.LMIS.value},
        user=owner,
    )
    assert not first.is_current
    assert not second.is_current
    # two claims coexist: the partial unique index never sees them
    assert application.submissions.filter(form_key="DHIS_CLAIM").count() == SECOND


# ---------------------------------------------------------------------------
# transition


def test_transition_refuses_an_illegal_move(application, owner):
    with pytest.raises(DomainError, match="not legal"):
        engine.transition(
            application=application,
            action="APPROVE",
            actor=owner,
        )


def test_submit_runs_the_registration_guard(application, owner):
    with pytest.raises(DomainError, match="complete the registration"):
        engine.transition(application=application, action="SUBMIT", actor=owner)

    engine.submit_form(
        application=application,
        form_key="REGISTRATION",
        cleaned_data=_registration_data(),
        user=owner,
    )
    record = engine.transition(
        application=application,
        action="SUBMIT",
        actor=owner,
    )
    assert record.to_state == "SUBMITTED"
    application.refresh_from_db()
    assert application.state == "SUBMITTED"


def test_sending_back_opens_the_next_round(application, owner):
    """The round turns when the work goes back, so everything the applicant
    then supplies is stamped with the round it answers. Bumping on the
    resubmission instead left the first send-back sharing round 1."""
    reviewer = UserFactory.create(is_staff=True)
    reviewer.user_permissions.add(
        Permission.objects.get(codename="send_back_abdm"),
    )
    engine.submit_form(
        application=application,
        form_key="REGISTRATION",
        cleaned_data=_registration_data(),
        user=owner,
    )
    engine.transition(application=application, action="SUBMIT", actor=owner)
    application.refresh_from_db()
    assert application.round == 1

    engine.transition(application=application, action="SEND_BACK", actor=reviewer)
    application.refresh_from_db()
    assert application.round == SECOND

    engine.transition(application=application, action="SUBMIT", actor=owner)
    application.refresh_from_db()
    assert application.round == SECOND
    assert application.state == "SUBMITTED"


def test_a_staff_move_needs_its_permission(application, owner):
    engine.submit_form(
        application=application,
        form_key="REGISTRATION",
        cleaned_data=_registration_data(),
        user=owner,
    )
    engine.transition(application=application, action="SUBMIT", actor=owner)
    powerless = UserFactory.create(is_staff=True)
    with pytest.raises(DomainError, match=r"requires workflow\.approve"):
        engine.transition(
            application=application,
            action="APPROVE",
            actor=powerless,
        )


def test_a_system_move_cannot_carry_an_actor(application, owner):
    engine.submit_form(
        application=application,
        form_key="REGISTRATION",
        cleaned_data=_registration_data(),
        user=owner,
    )
    engine.transition(application=application, action="SUBMIT", actor=owner)
    approver = UserFactory.create(is_staff=True)
    approver.user_permissions.add(
        Permission.objects.get(codename="approve_abdm"),
    )
    engine.transition(application=application, action="APPROVE", actor=approver)
    with pytest.raises(DomainError, match="system move"):
        engine.transition(
            application=application,
            action="START_PROVISIONING",
            actor=approver,
        )
    record = engine.transition(
        application=application,
        action="START_PROVISIONING",
    )
    assert record.to_state == "PROVISIONING"


def test_a_review_driven_move_refuses_a_transition_comment(application, owner):
    reviewer = UserFactory.create(is_staff=True)
    reviewer.user_permissions.add(
        Permission.objects.get(codename="send_back_abdm"),
    )
    engine.submit_form(
        application=application,
        form_key="REGISTRATION",
        cleaned_data=_registration_data(),
        user=owner,
    )
    engine.transition(application=application, action="SUBMIT", actor=owner)
    with pytest.raises(DomainError, match="review-driven"):
        engine.transition(
            application=application,
            action="SEND_BACK",
            actor=reviewer,
            comment="please fix the GSTIN",
        )


# ---------------------------------------------------------------------------
# The exit workflow: decisions, rounds, and the cross-application read


@pytest.fixture
def approver():
    user = UserFactory.create(is_staff=True)
    user.user_permissions.add(
        Permission.objects.get(codename="approve_abdm"),
    )
    user.user_permissions.add(
        Permission.objects.get(codename="reject_abdm"),
    )
    return user


@pytest.fixture
def exit_application(application, owner):
    """A PROVISIONED ABDM app with M1 declared, plus its exit under review."""
    application.state = "PROVISIONED"
    application.save(update_fields=["state"])
    engine.submit_form(
        application=application,
        form_key=milestone_form_key(Milestone.M1),
        cleaned_data={},
        user=owner,
    )
    return ApplicationFactory.create(
        workflow_key="ABDM_EXIT",
        state="UNDER_REVIEW",
        product=application.product,
        registered=False,
    )


def test_approve_writes_the_decision_in_the_same_transaction(
    exit_application,
    approver,
):
    record = engine.transition(
        application=exit_application,
        action="APPROVE",
        actor=approver,
        decision_data={"approved_solution_types": [SolutionType.HMIS.value]},
    )
    assert record.to_state == "APPROVED"
    decision = exit_application.submissions.get(form_key="EXIT_DECISION")
    assert decision.is_current
    assert decision.submitted_by == approver
    assert decision.data["approved_solution_types"] == [SolutionType.HMIS.value]


def test_approve_without_a_decision_is_refused(exit_application, approver):
    with pytest.raises(DomainError, match="requires the EXIT_DECISION"):
        engine.transition(
            application=exit_application,
            action="APPROVE",
            actor=approver,
        )
    exit_application.refresh_from_db()
    # the move and the decision are one unit: neither happened
    assert exit_application.state == "UNDER_REVIEW"
    assert not exit_application.submissions.exists()


def test_a_non_deciding_move_refuses_decision_data(exit_application, approver):
    with pytest.raises(DomainError, match="does not take a decision"):
        engine.transition(
            application=exit_application,
            action="REJECT",
            actor=approver,
            decision_data={"approved_solution_types": []},
        )


def test_rejecting_opens_the_next_round(exit_application, approver, owner):
    engine.transition(
        application=exit_application,
        action="REJECT",
        actor=approver,
    )
    exit_application.refresh_from_db()
    assert exit_application.state == "REJECTED"
    # the rejected attempt's WASA now belongs to a round that is over
    assert exit_application.round == SECOND

    engine.transition(
        application=exit_application,
        action="RESUBMIT",
        actor=owner,
    )
    exit_application.refresh_from_db()
    assert exit_application.state == "DRAFT"
    assert exit_application.round == SECOND


def test_the_exit_gate_reads_milestones_from_the_sibling_application(
    exit_application,
    owner,
):
    exit_application.state = "DRAFT"
    exit_application.save(update_fields=["state"])
    engine.submit_form(
        application=exit_application,
        form_key="EXIT_CLAIM",
        cleaned_data={"covers": [Milestone.M2.value], "summary": "HIP built."},
        user=owner,
    )
    engine.submit_form(
        application=exit_application,
        form_key="WASA",
        cleaned_data={"start": "2026-01-01", "valid_upto": "2027-01-01"},
        user=owner,
    )
    # M2 was never declared on the ABDM application
    with pytest.raises(DomainError, match="declare M2"):
        engine.transition(
            application=exit_application,
            action="SUBMIT",
            actor=owner,
        )


def test_a_carried_over_wasa_must_be_reaffirmed(
    exit_application,
    owner,
    approver,
):
    """Unexpired, so not re-uploaded — but somebody has to say it still holds."""
    claim, wasa = _claim_the_first_milestone(exit_application, owner)
    _evidence(claim, wasa, owner)
    exit_application.state = "UNDER_REVIEW"
    exit_application.save(update_fields=["state"])
    engine.transition(application=exit_application, action="REJECT", actor=approver)
    engine.transition(application=exit_application, action="RESUBMIT", actor=owner)

    with pytest.raises(DomainError, match="still stands"):
        engine.transition(
            application=exit_application,
            action="SUBMIT",
            actor=owner,
        )

    # restating it for this round is the affirmation; the certificate itself
    # carries forward, which is the point of not demanding a new upload
    engine.submit_form(
        application=exit_application,
        form_key="WASA",
        cleaned_data={"start": "2026-01-01", "valid_upto": "2027-01-01"},
        user=owner,
    )
    engine.transition(application=exit_application, action="SUBMIT", actor=owner)

    exit_application.refresh_from_db()
    assert exit_application.state == "SUBMITTED"


def test_an_expired_wasa_cannot_be_reaffirmed(exit_application, owner):
    """Validity is the rule the round only approximates: restating it in this
    round does not renew a lapsed audit."""
    claim, _wasa = _claim_the_first_milestone(exit_application, owner)
    yesterday = timezone.localdate() - timedelta(days=1)
    wasa = engine.submit_form(
        application=exit_application,
        form_key="WASA",
        cleaned_data={
            "start": "2020-01-01",
            "valid_upto": yesterday.isoformat(),
        },
        user=owner,
    )
    _evidence(claim, wasa, owner)

    with pytest.raises(DomainError, match="expired"):
        engine.transition(
            application=exit_application,
            action="SUBMIT",
            actor=owner,
        )


def test_a_wasa_valid_through_today_still_counts(exit_application, owner):
    """The boundary: a statement expires the day after it stops being valid."""
    claim, _wasa = _claim_the_first_milestone(exit_application, owner)
    wasa = engine.submit_form(
        application=exit_application,
        form_key="WASA",
        cleaned_data={
            "start": "2020-01-01",
            "valid_upto": timezone.localdate().isoformat(),
        },
        user=owner,
    )
    _evidence(claim, wasa, owner)

    engine.transition(application=exit_application, action="SUBMIT", actor=owner)

    exit_application.refresh_from_db()
    assert exit_application.state == "SUBMITTED"


def _claim_the_first_milestone(exit_application, owner):
    """Fill an exit's two owner forms, leaving only the evidence outstanding."""
    exit_application.state = "DRAFT"
    exit_application.save(update_fields=["state"])
    claim = engine.submit_form(
        application=exit_application,
        form_key="EXIT_CLAIM",
        cleaned_data={"covers": [Milestone.M1.value], "summary": "ABHA done."},
        user=owner,
    )
    wasa = engine.submit_form(
        application=exit_application,
        form_key="WASA",
        cleaned_data={"start": "2026-01-01", "valid_upto": "2027-01-01"},
        user=owner,
    )
    return claim, wasa


def _attach(submission, kind, owner):
    return ApplicationDocument.objects.create(
        submission=submission,
        kind=kind,
        storage_key=str(uuid.uuid4()),
        filename=f"{kind.lower()}.pdf",
        content_type="application/pdf",
        size=1024,
        sha256=hashlib.sha256(kind.encode()).hexdigest(),
        uploaded_by=owner,
    )


def _evidence(claim, wasa, owner):
    """Every document the exit gate demands, so a test can fail on its own rule."""
    for kind in ABDMExitWorkflow.form("EXIT_CLAIM").requires_document:
        _attach(claim, kind, owner)
    for kind in ABDMExitWorkflow.form("WASA").requires_document:
        _attach(wasa, kind, owner)


def test_the_exit_gate_names_the_evidence_that_is_missing(exit_application, owner):
    claim, _wasa = _claim_the_first_milestone(exit_application, owner)
    _attach(claim, DocumentKind.FUNCTIONAL_TEST_REPORT, owner)

    with pytest.raises(DomainError, match="EXIT_CLAIM needs the following evidence"):
        engine.transition(
            application=exit_application,
            action="SUBMIT",
            actor=owner,
        )


def test_a_fully_evidenced_exit_reaches_review(exit_application, owner):
    claim, wasa = _claim_the_first_milestone(exit_application, owner)
    _evidence(claim, wasa, owner)

    engine.transition(
        application=exit_application,
        action="SUBMIT",
        actor=owner,
    )

    exit_application.refresh_from_db()
    assert exit_application.state == "SUBMITTED"
