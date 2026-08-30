"""The exit half of the journey: request, review, and the reject/re-request loop."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile

from sandbox.applications.models import ApplicationState
from sandbox.applications.tests.factories import ApplicationFactory
from sandbox.audit.models import AuditEvent
from sandbox.catalog.tests.factories import MilestoneFactory
from sandbox.declarations import services as declarations
from sandbox.declarations.models import DeclarationKind
from sandbox.declarations.models import DeclarationState
from sandbox.declarations.selectors import current_exit_declaration
from sandbox.organisations.tests.factories import MembershipFactory
from sandbox.organisations.tests.factories import OrganisationFactory
from sandbox.organisations.tests.factories import ProductFactory
from sandbox.users.tests.factories import UserFactory
from sandbox.utils.errors import DomainError
from sandbox.workflow import selectors
from sandbox.workflow import services
from sandbox.workflow.machine import Action

pytestmark = pytest.mark.django_db

EVIDENCE = b"%PDF-1.7\ntrailer\n%%EOF\n"


def _grant(user, *codenames):
    for codename in codenames:
        user.user_permissions.add(Permission.objects.get(codename=codename))
    # a fresh instance: the permission cache is per-instance and already warm
    return type(user).objects.get(pk=user.pk)


def _upload(name="exit.pdf"):
    return SimpleUploadedFile(name, EVIDENCE, content_type="application/pdf")


@pytest.fixture
def org(db):
    return OrganisationFactory.create()


@pytest.fixture
def owner(org):
    user = UserFactory.create()
    MembershipFactory.create(organisation=org, user=user)
    return user


@pytest.fixture
def admin(db):
    return _grant(
        UserFactory.create(is_staff=True),
        "approve_application",
        "reject_application",
        "send_back_application",
        "review_application",
    )


@pytest.fixture
def application(org, owner):
    return ApplicationFactory.create(
        product=ProductFactory.create(organisation=org),
        applicant=owner,
        state=ApplicationState.PROVISIONED,
    )


@pytest.fixture
def milestone(db):
    return MilestoneFactory.create(key="m1")


def _declare(application, milestone, owner):
    declarations.submit_milestone_declaration(
        application=application,
        milestone=milestone,
        actor=owner,
    )


def _exit_bundle(application, milestones, owner, files=None):
    return declarations.submit_exit_declaration(
        application=application,
        milestones=milestones,
        actor=owner,
        files=[_upload()] if files is None else files,
    )


def _ready_to_exit(application, milestone, owner):
    _declare(application, milestone, owner)
    return _exit_bundle(application, [milestone], owner)


# The guard


def test_exit_without_a_declaration_is_refused(application, owner):
    with pytest.raises(DomainError) as exc:
        services.request_exit(application=application, actor=owner)

    assert exc.value.code == "no_exit_declaration"
    application.refresh_from_db()
    assert application.state == ApplicationState.PROVISIONED


def test_exit_without_documents_is_refused(application, milestone, owner):
    _declare(application, milestone, owner)
    _exit_bundle(application, [milestone], owner, files=[])

    with pytest.raises(DomainError) as exc:
        services.request_exit(application=application, actor=owner)
    assert exc.value.code == "no_exit_documents"


def test_exiting_an_undeclared_milestone_is_refused(
    mock_s3,
    application,
    milestone,
    owner,
):
    """You cannot take M1 to production without having declared M1 done."""
    _exit_bundle(application, [milestone], owner)

    with pytest.raises(DomainError) as exc:
        services.request_exit(application=application, actor=owner)
    assert exc.value.code == "milestone_not_declared"
    assert milestone.key in exc.value.message


def test_exiting_does_not_require_declaring_unrelated_milestones(
    mock_s3,
    application,
    milestone,
    owner,
):
    """Exiting M1 must not oblige an integrator to declare M2 as well."""
    MilestoneFactory.create(key="m2")
    _ready_to_exit(application, milestone, owner)

    services.request_exit(application=application, actor=owner)
    application.refresh_from_db()
    assert application.state == ApplicationState.EXIT_REQUESTED


def test_the_guard_cannot_be_bypassed_by_calling_transition_directly(
    application,
    owner,
):
    """The guard lives on the table, so the console reaches it too."""
    with pytest.raises(DomainError) as exc:
        services.transition(
            application=application,
            action=Action.REQUEST_EXIT,
            actor=owner,
        )
    assert exc.value.code == "no_exit_declaration"


def test_a_non_member_cannot_request_exit(mock_s3, application, milestone, owner):
    _ready_to_exit(application, milestone, owner)

    with pytest.raises(DomainError) as exc:
        services.request_exit(application=application, actor=UserFactory.create())
    assert exc.value.code == "forbidden"


# The happy path


def test_the_full_exit_path_reaches_production_approved(
    mock_s3,
    application,
    milestone,
    owner,
    admin,
):
    declaration = _ready_to_exit(application, milestone, owner)

    services.request_exit(application=application, actor=owner)
    services.transition(
        application=application,
        action=Action.START_EXIT_REVIEW,
        actor=admin,
    )
    services.transition(
        application=application,
        action=Action.APPROVE_EXIT,
        actor=admin,
    )

    application.refresh_from_db()
    declaration.refresh_from_db()
    assert application.state == ApplicationState.PRODUCTION_APPROVED
    assert declaration.state == DeclarationState.APPROVED


def test_approval_settles_the_declaration_so_a7_protects_it(
    mock_s3,
    application,
    milestone,
    owner,
    admin,
):
    """The whole point of settling: A7 then refuses to supersede the claim."""
    _ready_to_exit(application, milestone, owner)
    services.request_exit(application=application, actor=owner)
    services.transition(
        application=application,
        action=Action.START_EXIT_REVIEW,
        actor=admin,
    )
    services.transition(
        application=application,
        action=Action.APPROVE_EXIT,
        actor=admin,
    )

    with pytest.raises(DomainError) as exc:
        declarations.submit_exit_declaration(
            application=application,
            milestones=[milestone],
            actor=owner,
        )
    # PRODUCTION_APPROVED is terminal, so the state guard answers first
    assert exc.value.code == "illegal_state"


def test_only_the_admin_permission_approves_an_exit(
    mock_s3,
    application,
    milestone,
    owner,
    admin,
):
    """A reviewer may start the review but not decide it."""
    reviewer = _grant(UserFactory.create(is_staff=True), "review_application")
    _ready_to_exit(application, milestone, owner)
    services.request_exit(application=application, actor=owner)
    services.transition(
        application=application,
        action=Action.START_EXIT_REVIEW,
        actor=admin,
    )

    with pytest.raises(DomainError) as exc:
        services.transition(
            application=application,
            action=Action.APPROVE_EXIT,
            actor=reviewer,
        )
    assert exc.value.code == "forbidden"


def test_an_owner_cannot_approve_their_own_exit(
    mock_s3,
    application,
    milestone,
    owner,
    admin,
):
    _ready_to_exit(application, milestone, owner)
    services.request_exit(application=application, actor=owner)
    services.transition(
        application=application,
        action=Action.START_EXIT_REVIEW,
        actor=admin,
    )

    with pytest.raises(DomainError) as exc:
        services.transition(
            application=application,
            action=Action.APPROVE_EXIT,
            actor=owner,
        )
    assert exc.value.code == "forbidden"


# Reject and re-request


def test_rejection_settles_the_declaration_and_allows_a_fresh_one(
    mock_s3,
    application,
    milestone,
    owner,
    admin,
):
    rejected = _ready_to_exit(application, milestone, owner)
    services.request_exit(application=application, actor=owner)
    services.transition(
        application=application,
        action=Action.START_EXIT_REVIEW,
        actor=admin,
    )
    services.transition(
        application=application,
        action=Action.REJECT_EXIT,
        actor=admin,
    )

    application.refresh_from_db()
    rejected.refresh_from_db()
    assert application.state == ApplicationState.EXIT_REJECTED
    assert rejected.state == DeclarationState.REJECTED

    # the re-request loop: a fresh declaration, superseding the rejected claim
    replacement = _exit_bundle(application, [milestone], owner)
    services.request_exit(application=application, actor=owner)

    application.refresh_from_db()
    assert application.state == ApplicationState.EXIT_REQUESTED
    assert current_exit_declaration(application) == replacement


def test_the_rejected_bundle_stays_readable_after_re_request(
    mock_s3,
    application,
    milestone,
    owner,
    admin,
):
    rejected = _ready_to_exit(application, milestone, owner)
    services.request_exit(application=application, actor=owner)
    services.transition(
        application=application,
        action=Action.START_EXIT_REVIEW,
        actor=admin,
    )
    services.transition(
        application=application,
        action=Action.REJECT_EXIT,
        actor=admin,
    )
    replacement = _exit_bundle(application, [milestone], owner)

    rejected.refresh_from_db()
    assert rejected.deleted is False
    assert rejected.documents.count() == 1
    assert rejected.milestones.get().superseded_by == replacement


def test_send_back_returns_to_provisioned_and_settles_the_bundle(
    mock_s3,
    application,
    milestone,
    owner,
    admin,
):
    """Exit send-back returns to PROVISIONED, not SENT_BACK."""
    declaration = _ready_to_exit(application, milestone, owner)
    services.request_exit(application=application, actor=owner)
    services.transition(
        application=application,
        action=Action.START_EXIT_REVIEW,
        actor=admin,
    )
    services.transition(
        application=application,
        action=Action.SEND_BACK_EXIT,
        actor=admin,
    )

    application.refresh_from_db()
    declaration.refresh_from_db()
    assert application.state == ApplicationState.PROVISIONED
    assert declaration.state == DeclarationState.REJECTED
    assert current_exit_declaration(application) is None


# Audit and selectors


def test_every_exit_move_is_audited(mock_s3, application, milestone, owner, admin):
    _ready_to_exit(application, milestone, owner)
    services.request_exit(application=application, actor=owner)
    services.transition(
        application=application,
        action=Action.START_EXIT_REVIEW,
        actor=admin,
    )
    services.transition(
        application=application,
        action=Action.APPROVE_EXIT,
        actor=admin,
    )

    actions = set(AuditEvent.objects.values_list("action", flat=True))
    assert {
        "application.request_exit",
        "application.start_exit_review",
        "application.approve_exit",
        "declaration.approved",
    } <= actions


def test_the_exit_queue_holds_applications_awaiting_a_decision(
    mock_s3,
    application,
    milestone,
    owner,
    admin,
):
    _ready_to_exit(application, milestone, owner)
    assert not selectors.exit_queue().exists()

    services.request_exit(application=application, actor=owner)
    assert list(selectors.exit_queue()) == [application]

    services.transition(
        application=application,
        action=Action.START_EXIT_REVIEW,
        actor=admin,
    )
    assert list(selectors.exit_queue()) == [application]

    services.transition(
        application=application,
        action=Action.APPROVE_EXIT,
        actor=admin,
    )
    assert not selectors.exit_queue().exists()


def test_the_current_exit_declaration_ignores_milestone_declarations(
    mock_s3,
    application,
    milestone,
    owner,
):
    _declare(application, milestone, owner)
    assert current_exit_declaration(application) is None

    bundle = _exit_bundle(application, [milestone], owner)
    assert current_exit_declaration(application) == bundle
    assert bundle.kind == DeclarationKind.EXIT


def test_a_bundle_replaced_before_review_is_not_the_current_one(
    mock_s3,
    application,
    milestone,
    owner,
):
    """Both are SUBMITTED, so only the claim tells them apart."""
    superseded = _exit_bundle(application, [milestone], owner)
    replacement = _exit_bundle(application, [milestone], owner)

    superseded.refresh_from_db()
    assert superseded.state == DeclarationState.SUBMITTED
    assert current_exit_declaration(application) == replacement


def test_a_rejected_bundle_is_not_the_current_one(
    mock_s3,
    application,
    milestone,
    owner,
    admin,
):
    """Rejection releases no claims, so only the state tells them apart."""
    rejected = _ready_to_exit(application, milestone, owner)
    services.request_exit(application=application, actor=owner)
    services.transition(
        application=application,
        action=Action.START_EXIT_REVIEW,
        actor=admin,
    )
    services.transition(
        application=application,
        action=Action.REJECT_EXIT,
        actor=admin,
    )

    assert rejected.milestones.get().superseded_by is None
    assert current_exit_declaration(application) is None


def test_a_rejected_bundle_cannot_be_re_requested_unchanged(
    mock_s3,
    application,
    milestone,
    owner,
    admin,
):
    """The re-request edge exists, but it needs a new bundle to act on."""
    _ready_to_exit(application, milestone, owner)
    services.request_exit(application=application, actor=owner)
    services.transition(
        application=application,
        action=Action.START_EXIT_REVIEW,
        actor=admin,
    )
    services.transition(
        application=application,
        action=Action.REJECT_EXIT,
        actor=admin,
    )

    with pytest.raises(DomainError) as exc:
        services.request_exit(application=application, actor=owner)
    assert exc.value.code == "no_exit_declaration"


def test_an_abandoned_bundle_cannot_stand_in_after_its_replacement_is_rejected(
    mock_s3,
    application,
    milestone,
    owner,
    admin,
):
    """An older SUBMITTED bundle is still abandoned, however new the rejection.

    Ordering alone cannot tell these apart: the abandoned one is *older* than
    the rejected one, so picking "the newest SUBMITTED exit" would resurrect it
    and let the integrator re-request without submitting anything new.
    """
    _declare(application, milestone, owner)
    abandoned = _exit_bundle(application, [milestone], owner)
    replacement = _exit_bundle(application, [milestone], owner)

    services.request_exit(application=application, actor=owner)
    services.transition(
        application=application,
        action=Action.START_EXIT_REVIEW,
        actor=admin,
    )
    services.transition(
        application=application,
        action=Action.REJECT_EXIT,
        actor=admin,
    )

    abandoned.refresh_from_db()
    replacement.refresh_from_db()
    assert abandoned.state == DeclarationState.SUBMITTED  # never reviewed
    assert replacement.state == DeclarationState.REJECTED

    assert current_exit_declaration(application) is None
    with pytest.raises(DomainError) as exc:
        services.request_exit(application=application, actor=owner)
    assert exc.value.code == "no_exit_declaration"
