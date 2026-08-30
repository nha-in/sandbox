"""`transition()` — authority, atomicity, audit, and on-commit side effects."""

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
from sandbox.workflow import services
from sandbox.workflow.machine import Action
from sandbox.workflow.models import WorkflowTransition
from sandbox.workflow.services import transition

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _no_hooks():
    services.clear_hooks()
    yield
    services.clear_hooks()


@pytest.fixture
def application():
    return ApplicationFactory.create()


@pytest.fixture
def owner(application):
    user = UserFactory.create()
    MembershipFactory.create(organisation=application.product.organisation, user=user)
    return user


def grant(user: User, codename: str) -> User:
    user.user_permissions.add(Permission.objects.get(codename=codename))
    # a fresh instance: the permission cache is per-instance and already warm
    return User.objects.get(pk=user.pk)


@pytest.fixture
def approver():
    return grant(UserFactory.create(is_staff=True), "approve_application")


# Guards


def test_submit_refuses_an_incomplete_payload(application, owner):
    """Drafts may be half-finished, so SUBMIT is where completeness is enforced."""
    application.payload = {"schema_version": 1, "data": {}}
    application.save(update_fields=["payload"])

    with pytest.raises(DomainError) as excinfo:
        transition(application=application, action=Action.SUBMIT, actor=owner)

    assert "required" in str(excinfo.value).lower()
    application.refresh_from_db()
    assert application.state == ApplicationState.DRAFT
    assert not WorkflowTransition.objects.filter(application=application).exists()


def test_a_guard_that_is_not_registered_blocks_the_move(
    application,
    owner,
    monkeypatch,
):
    """Fail closed: a missing registration must not silently skip the check."""
    monkeypatch.setattr(services, "_GUARDS", {})

    with pytest.raises(DomainError) as excinfo:
        transition(application=application, action=Action.SUBMIT, actor=owner)

    assert excinfo.value.code == "guard_unavailable"
    application.refresh_from_db()
    assert application.state == ApplicationState.DRAFT


# Legality


def test_legal_move_updates_state_and_writes_one_row(application, owner):
    record = transition(application=application, action=Action.SUBMIT, actor=owner)

    application.refresh_from_db()
    assert application.state == ApplicationState.SUBMITTED
    assert record.from_state == ApplicationState.DRAFT
    assert record.to_state == ApplicationState.SUBMITTED
    assert WorkflowTransition.objects.count() == 1


def test_illegal_move_is_refused(application, approver):
    with pytest.raises(DomainError) as excinfo:
        transition(application=application, action=Action.APPROVE, actor=approver)

    assert excinfo.value.code == "illegal_transition"


def test_illegal_move_leaves_no_rows(application, approver):
    with pytest.raises(DomainError):
        transition(application=application, action=Action.APPROVE, actor=approver)

    application.refresh_from_db()
    assert application.state == ApplicationState.DRAFT
    assert WorkflowTransition.objects.count() == 0
    assert AuditEvent.objects.count() == 0


# Authority


def test_staff_move_without_the_permission_is_refused(application, owner):
    transition(application=application, action=Action.SUBMIT, actor=owner)

    with pytest.raises(DomainError) as excinfo:
        transition(application=application, action=Action.APPROVE, actor=owner)

    assert excinfo.value.code == "forbidden"


def test_staff_move_with_the_permission_succeeds(application, owner, approver):
    transition(application=application, action=Action.SUBMIT, actor=owner)

    transition(application=application, action=Action.APPROVE, actor=approver)

    application.refresh_from_db()
    assert application.state == ApplicationState.SANDBOX_APPROVED


def test_owner_move_by_a_non_member_is_refused(application):
    stranger = UserFactory.create()

    with pytest.raises(DomainError) as excinfo:
        transition(application=application, action=Action.SUBMIT, actor=stranger)

    assert excinfo.value.code == "forbidden"


def test_system_move_rejects_an_actor(application, owner, approver):
    transition(application=application, action=Action.SUBMIT, actor=owner)
    transition(application=application, action=Action.APPROVE, actor=approver)

    with pytest.raises(DomainError) as excinfo:
        transition(
            application=application,
            action=Action.START_PROVISIONING,
            actor=approver,
        )

    assert excinfo.value.code == "forbidden"


def test_system_move_succeeds_without_an_actor(application, owner, approver):
    transition(application=application, action=Action.SUBMIT, actor=owner)
    transition(application=application, action=Action.APPROVE, actor=approver)

    record = transition(application=application, action=Action.START_PROVISIONING)

    assert record.actor is None
    application.refresh_from_db()
    assert application.state == ApplicationState.PROVISIONING


def test_owner_move_requires_an_actor(application):
    with pytest.raises(DomainError) as excinfo:
        transition(application=application, action=Action.SUBMIT)

    assert excinfo.value.code == "forbidden"


# Audit


def test_every_transition_emits_exactly_one_audit_event(application, owner):
    transition(application=application, action=Action.SUBMIT, actor=owner)

    events = AuditEvent.objects.all()
    assert len(events) == 1
    event = events[0]
    assert event.action == "application.submit"
    assert event.actor == owner
    assert event.object_external_id == application.external_id
    assert event.data["from_state"] == ApplicationState.DRAFT
    assert event.data["to_state"] == ApplicationState.SUBMITTED
    assert event.correlation_id


def test_audit_events_share_a_correlation_id_within_a_context(application, owner):
    transition(application=application, action=Action.SUBMIT, actor=owner)
    transition(application=application, action=Action.WITHDRAW, actor=owner)

    ids = {event.correlation_id for event in AuditEvent.objects.all()}
    assert len(ids) == 1


# Side effects


def test_hooks_fire_only_after_commit(
    application,
    owner,
    approver,
    django_capture_on_commit_callbacks,
):
    fired = []
    services.register_hook("provisioning_chain", lambda app, rec: fired.append(app.pk))
    transition(application=application, action=Action.SUBMIT, actor=owner)

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        transition(application=application, action=Action.APPROVE, actor=approver)
        assert fired == []  # still inside the transaction

    assert len(callbacks) == 1
    callbacks[0]()
    assert fired == [application.pk]


def test_unregistered_hooks_are_a_no_op(application, owner, approver):
    """A5 ships before B7 registers the chain; approval must still work."""
    transition(application=application, action=Action.SUBMIT, actor=owner)

    transition(application=application, action=Action.APPROVE, actor=approver)

    application.refresh_from_db()
    assert application.state == ApplicationState.SANDBOX_APPROVED


# Comments are single-homed


def test_review_driven_move_refuses_a_transition_comment(application, owner, approver):
    """03-database.md: the review row is the single home for that text."""
    transition(application=application, action=Action.SUBMIT, actor=owner)

    with pytest.raises(DomainError) as excinfo:
        transition(
            application=application,
            action=Action.APPROVE,
            actor=approver,
            comment="looks good to me",
        )

    assert excinfo.value.code == "comment_not_allowed"


def test_review_driven_move_without_a_comment_is_fine(application, owner, approver):
    transition(application=application, action=Action.SUBMIT, actor=owner)

    record = transition(application=application, action=Action.APPROVE, actor=approver)

    assert record.comment == ""


def test_non_review_move_keeps_its_comment(application, owner):
    """Withdrawal has no review behind it, so the reason lives here."""
    record = transition(
        application=application,
        action=Action.WITHDRAW,
        actor=owner,
        comment="duplicate application",
    )

    assert record.comment == "duplicate application"
