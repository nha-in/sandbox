"""Plan 12 §6's engine delta, and §5's access control."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError

from sandbox.experiences import permission_keys
from sandbox.experiences.definitions import ActionResult
from sandbox.experiences.models import ApplicationAccess
from sandbox.experiences.models import ApplicationInstance
from sandbox.experiences.models import ReviewRole
from sandbox.experiences.models import ReviewRoleAssignment
from sandbox.experiences.models import declared_permission_keys
from sandbox.experiences.permissions import get_effective_access
from sandbox.experiences.registry import registry
from sandbox.experiences.services import create_application
from sandbox.experiences.services import perform_application_action
from sandbox.organisations.models import Membership
from sandbox.organisations.models import Role
from sandbox.organisations.tests.factories import OrganisationFactory
from sandbox.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

APPLICATION_TYPE = "abdm_production_access"


@pytest.fixture
def owner_user(db):
    return UserFactory.create(email="owner@vendor.in")


@pytest.fixture
def decision_maker_role(db):
    return ReviewRole.objects.get(key="decision_maker")


@pytest.fixture
def reviewer_role(db):
    return ReviewRole.objects.get(key="reviewer")


def _holding(role, email):
    user = UserFactory.create(email=email)
    ReviewRoleAssignment.objects.create(user=user, role=role)
    return user


@pytest.fixture
def ohc_user(decision_maker_role):
    return _holding(decision_maker_role, "reviewer@nha.gov.in")


@pytest.fixture
def abdm_application(owner_user, ohc_user):
    organisation = OrganisationFactory(onboarded=True)
    Membership.objects.create(
        organisation=organisation,
        user=owner_user,
        role=Role.OWNER,
    )
    application = create_application(
        application_type=APPLICATION_TYPE,
        organisation=organisation,
        user=owner_user,
    )
    ApplicationAccess.objects.create(
        application=application,
        user=ohc_user,
        role_key="decision_maker",
        granted_by=ohc_user,
    )
    return application


# ── E1: ActionResult.effects ─────────────────────────────────────────────────


def test_an_action_declaring_no_effects_behaves_exactly_as_before():
    """E1 is additive; every existing definition declares none."""
    result = ActionResult(message="Submitted")

    assert result.effects == ()


def test_effects_run_only_after_the_transaction_commits(
    abdm_application,
    ohc_user,
    monkeypatch,
    django_capture_on_commit_callbacks,
):
    """An effect provisions credentials. It must never see a rolled-back write."""
    ran: list[str] = []

    def effect(application, user) -> None:
        ran.append(application.reference)

    _submitted(abdm_application)
    _declare_effects(monkeypatch, abdm_application, "start_review", (effect,))

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        perform_application_action(
            application=abdm_application,
            action_key="start_review",
            user=ohc_user,
        )
        # The action has returned, and the effect has still not run: it is
        # queued against the commit, which is the whole point of E1.
        assert ran == []

    assert len(callbacks) == 1
    assert ran == [abdm_application.reference]


def test_an_effect_is_given_the_application_and_the_actor(
    abdm_application,
    ohc_user,
    monkeypatch,
    django_capture_on_commit_callbacks,
):
    seen: list[tuple] = []

    _submitted(abdm_application)
    _declare_effects(
        monkeypatch,
        abdm_application,
        "start_review",
        (lambda application, user: seen.append((application.pk, user.pk)),),
    )

    with django_capture_on_commit_callbacks(execute=True):
        perform_application_action(
            application=abdm_application,
            action_key="start_review",
            user=ohc_user,
        )

    assert seen == [(abdm_application.pk, ohc_user.pk)]


# ── §5: NHA roles are data, permissions are code ────────────────────────────


def test_the_three_roles_are_seeded(db):
    """A portal with no review roles cannot be reviewed."""
    assert set(ReviewRole.objects.values_list("key", flat=True)) == {
        "review_observer",
        "reviewer",
        "decision_maker",
    }


def test_a_role_may_only_hold_permissions_the_registry_declares():
    """The safety property. Legacy could name a permission nothing checked."""
    role = ReviewRole(key="invented", name="Invented", permissions=["not.a.key"])

    with pytest.raises(ValidationError) as caught:
        role.full_clean()

    assert "not.a.key" in str(caught.value)


def test_every_seeded_permission_is_declared():
    declared = declared_permission_keys()

    for role in ReviewRole.objects.all():
        assert set(role.permissions) <= declared, role.key


def test_a_standing_role_sees_every_application_without_a_grant(
    abdm_application,
    reviewer_role,
):
    """The point of the standing grant: no row per application."""
    reviewer = _holding(reviewer_role, "r@nha.gov.in")

    visible = ApplicationInstance.objects.visible_to(reviewer)

    assert abdm_application in visible
    assert not abdm_application.access_grants.filter(user=reviewer).exists()


def test_a_standing_role_carries_its_permissions_without_a_grant(
    abdm_application,
    reviewer_role,
):
    reviewer = _holding(reviewer_role, "r@nha.gov.in")

    access = get_effective_access(abdm_application, reviewer)

    assert access.grant is None
    assert access.allows(permission_keys.REVIEW_APPLICATION)
    assert not access.allows(permission_keys.APPROVE_APPLICATION)


def test_a_decision_maker_may_approve_and_a_reviewer_may_not(
    abdm_application,
    reviewer_role,
    decision_maker_role,
):
    decider = _holding(decision_maker_role, "d@nha.gov.in")
    reviewer = _holding(reviewer_role, "r@nha.gov.in")

    assert get_effective_access(abdm_application, decider).allows(
        permission_keys.APPROVE_APPLICATION,
    )
    assert not get_effective_access(abdm_application, reviewer).allows(
        permission_keys.APPROVE_APPLICATION,
    )


def test_a_role_with_no_permissions_sees_nothing(abdm_application, db):
    """Legacy's User_view holds no permissions; migrating it must grant nothing.

    Visibility follows the permission, not the bare fact of holding a role —
    otherwise an empty role would be the most powerful thing in the system.
    """
    empty = ReviewRole.objects.create(key="user_view", name="User view")
    person = _holding(empty, "empty@nha.gov.in")

    assert abdm_application not in ApplicationInstance.objects.visible_to(person)
    assert get_effective_access(abdm_application, person).permissions == frozenset()


def test_deactivating_a_role_withdraws_it_everywhere_at_once(
    abdm_application,
    reviewer_role,
):
    """Editable roles are only safe if switching one off actually takes effect."""
    reviewer = _holding(reviewer_role, "r@nha.gov.in")
    reviewer_role.is_active = False
    reviewer_role.save(update_fields=["is_active"])

    assert abdm_application not in ApplicationInstance.objects.visible_to(reviewer)
    assert not get_effective_access(abdm_application, reviewer).allows(
        permission_keys.REVIEW_APPLICATION,
    )


def test_two_roles_union_rather_than_conflict(
    abdm_application,
    reviewer_role,
    decision_maker_role,
):
    """One role per user was a legacy limitation, not a rule (§5.2)."""
    person = _holding(reviewer_role, "both@nha.gov.in")
    ReviewRoleAssignment.objects.create(user=person, role=decision_maker_role)

    access = get_effective_access(abdm_application, person)

    assert access.allows(permission_keys.APPROVE_APPLICATION)
    assert access.allows(permission_keys.REVIEW_APPLICATION)


def test_a_standing_role_adds_to_an_applicant_grant_rather_than_replacing_it(
    abdm_application,
    owner_user,
    reviewer_role,
):
    """Someone who is both keeps both. The grant is not overwritten."""
    ReviewRoleAssignment.objects.create(user=owner_user, role=reviewer_role)

    access = get_effective_access(abdm_application, owner_user)

    assert access.allows(permission_keys.SUBMIT_APPLICATION)
    assert access.allows(permission_keys.REVIEW_APPLICATION)


def test_an_integrator_still_sees_only_their_own(abdm_application):
    stranger = UserFactory.create()

    assert abdm_application not in ApplicationInstance.objects.visible_to(stranger)


def test_the_applicant_still_sees_their_own(abdm_application):
    creator = abdm_application.created_by

    assert abdm_application in ApplicationInstance.objects.visible_to(creator)


def test_an_anonymous_visitor_sees_nothing(abdm_application):
    assert not ApplicationInstance.objects.visible_to(AnonymousUser()).exists()


# ── E4: withdrawal is reachable ──────────────────────────────────────────────


def test_the_owner_can_withdraw_a_submitted_application(abdm_application, owner_user):
    abdm_application.status = "submitted"
    abdm_application.save(update_fields=["status"])

    result, _ = perform_application_action(
        application=abdm_application,
        action_key="withdraw",
        user=owner_user,
    )
    abdm_application.refresh_from_db()

    assert result.new_status == "withdrawn"
    assert abdm_application.status == "withdrawn"
    assert abdm_application.outcome["withdrawn_by"] == owner_user.pk


def test_withdrawal_is_terminal(abdm_application, owner_user):
    """No action reaches a withdrawn application; a fresh one is the way back."""
    abdm_application.status = "withdrawn"
    abdm_application.save(update_fields=["status"])

    with pytest.raises(PermissionDenied):
        perform_application_action(
            application=abdm_application,
            action_key="withdraw",
            user=owner_user,
        )


def test_withdrawing_is_recorded_with_its_actor(abdm_application, owner_user):
    abdm_application.status = "submitted"
    abdm_application.save(update_fields=["status"])

    perform_application_action(
        application=abdm_application,
        action_key="withdraw",
        user=owner_user,
    )
    event = abdm_application.events.filter(action_key="withdraw").get()

    assert event.actor == owner_user
    assert event.status_before == "submitted"
    assert event.status_after == "withdrawn"


def test_a_decided_application_cannot_be_withdrawn(abdm_application, owner_user):
    abdm_application.status = "approved"
    abdm_application.save(update_fields=["status"])

    with pytest.raises(PermissionDenied):
        perform_application_action(
            application=abdm_application,
            action_key="withdraw",
            user=owner_user,
        )


def _submitted(application):
    application.status = "submitted"
    application.save(update_fields=["status"])


def _declare_effects(monkeypatch, application, action_key, effects):
    """Make one action declare `effects`, without leaking into the next test.

    No definition declares any yet — E1 is the seam they arrive through — so
    exercising it means adding one here rather than waiting for step 5.
    """
    action = registry.get(application.application_type).get_action(action_key)
    original = action.perform

    def perform(context, cleaned_data):
        result = original(context, cleaned_data)
        return ActionResult(
            message=result.message,
            new_status=result.new_status,
            metadata_updates=result.metadata_updates,
            outcome_updates=result.outcome_updates,
            query=result.query,
            effects=effects,
        )

    monkeypatch.setattr(action, "perform", perform)
