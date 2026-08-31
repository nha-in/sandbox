"""The five lifecycle hooks A5 declared and nobody answered until B6."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Permission

from sandbox.applications.tests.factories import ApplicationFactory
from sandbox.notifications.hooks import HOOK_TEMPLATES
from sandbox.notifications.hooks import register_workflow_hooks
from sandbox.notifications.models import Message
from sandbox.notifications.models import TemplateKey
from sandbox.notifications.services import SECRET_KEY_FRAGMENTS
from sandbox.organisations.tests.factories import MembershipFactory
from sandbox.users.models import User
from sandbox.users.tests.factories import UserFactory
from sandbox.workflow import engine as workflow_engine
from sandbox.workflow import services
from sandbox.workflow.engine import transition
from sandbox.workflow.models import ReviewDecision
from sandbox.workflow.registry import WORKFLOWS

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _hooks():
    """Other suites call `clear_hooks()`, which wipes what `ready()` registered."""
    workflow_engine.clear_hooks()
    register_workflow_hooks()
    yield
    workflow_engine.clear_hooks()


@pytest.fixture
def application():
    return ApplicationFactory.create()


@pytest.fixture
def owner(application):
    user = UserFactory.create()
    MembershipFactory.create(organisation=application.product.organisation, user=user)
    return user


def _staff(*codenames: str) -> User:
    user = UserFactory.create(is_staff=True)
    for codename in codenames:
        user.user_permissions.add(Permission.objects.get(codename=codename))
    # a fresh instance: the permission cache is per-instance and already warm
    return User.objects.get(pk=user.pk)


def test_every_declared_notify_hook_has_a_template() -> None:
    """A hook name with no template is an email nobody ever sends.

    Every registered workflow, not just the sandbox one: an unregistered hook
    is a silent no-op in the engine, so a missing exit template would never
    announce itself.
    """
    declared = {
        hook
        for workflow in WORKFLOWS.values()
        for spec in workflow.transitions.values()
        for hook in spec.hooks
        if hook.startswith("notify_")
    }
    assert declared == set(HOOK_TEMPLATES)


def test_rejection_emails_the_applicant(
    application,
    owner,
    django_capture_on_commit_callbacks,
):
    reviewer = _staff("reject_application")
    transition(application=application, action="SUBMIT", actor=owner)

    with django_capture_on_commit_callbacks(execute=True):
        transition(application=application, action="REJECT", actor=reviewer)

    message = Message.objects.get()
    assert message.template_key == TemplateKey.SANDBOX_REJECTED
    assert message.recipient == application.applicant.email
    assert message.params["reference"] == application.reference
    assert message.application == application


def test_a_rejection_quotes_the_reviewers_note(
    application,
    owner,
    django_capture_on_commit_callbacks,
):
    """The text lives on A6's review row, so the hook has to go and find it."""
    reviewer = _staff("review_application", "reject_application")
    transition(application=application, action="SUBMIT", actor=owner)
    services.record_review(
        application=application,
        reviewer=reviewer,
        decision=ReviewDecision.REJECT,
        comment="Your HIP callback is not reachable.",
    )

    with django_capture_on_commit_callbacks(execute=True):
        transition(application=application, action="REJECT", actor=reviewer)

    assert Message.objects.get().params["comment"] == (
        "Your HIP callback is not reachable."
    )


def test_provisioned_emails_a_link_and_never_a_credential(
    application,
    owner,
    django_capture_on_commit_callbacks,
):
    approver = _staff("approve_application")
    transition(application=application, action="SUBMIT", actor=owner)
    transition(application=application, action="APPROVE", actor=approver)
    transition(application=application, action="START_PROVISIONING")

    with django_capture_on_commit_callbacks(execute=True):
        transition(application=application, action="COMPLETE_PROVISIONING")

    message = Message.objects.get(template_key=TemplateKey.SANDBOX_APPROVED)
    assert str(application.external_id) in message.params["panel_url"]
    body = " ".join(f"{key} {value}" for key, value in message.params.items()).lower()
    assert not any(fragment in body for fragment in SECRET_KEY_FRAGMENTS)
