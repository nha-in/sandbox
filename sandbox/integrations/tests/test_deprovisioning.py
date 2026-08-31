"""B8 acceptance criteria — the reverse chain, and what it refuses to leave on."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Permission
from django.test import override_settings

from sandbox.applications.models import ApplicationState
from sandbox.applications.tests.factories import ApplicationFactory
from sandbox.audit.models import AuditEvent
from sandbox.integrations import fakes
from sandbox.integrations.fakes import always_fail
from sandbox.integrations.fakes import fail_next
from sandbox.integrations.hooks import register_workflow_hooks
from sandbox.integrations.models import ProvisionedResource
from sandbox.integrations.models import ProvisionedResourceState
from sandbox.integrations.models import ProvisionedSystem
from sandbox.integrations.ports import ExternalSystem
from sandbox.integrations.services import retry_deprovisioning
from sandbox.notifications import hooks as notification_hooks
from sandbox.notifications.models import Message
from sandbox.notifications.models import TemplateKey
from sandbox.organisations.tests.factories import MembershipFactory
from sandbox.programmes.abdm import ABDMWorkflow
from sandbox.users.models import User
from sandbox.users.tests.factories import UserFactory
from sandbox.utils.errors import DomainError
from sandbox.workflow import engine as workflow_engine
from sandbox.workflow.engine import transition

pytestmark = pytest.mark.django_db

ALL_SYSTEMS = set(ProvisionedSystem.values)


@pytest.fixture(autouse=True)
def _hooks():
    workflow_engine.clear_hooks()
    register_workflow_hooks()
    notification_hooks.register_workflow_hooks()
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


def _provision(application, owner, callbacks) -> None:
    transition(application=application, action="SUBMIT", actor=owner)
    with callbacks(execute=True):
        transition(
            application=application,
            action="APPROVE",
            actor=_staff("approve_application"),
        )
    application.refresh_from_db()


def _states(application) -> dict[str, str]:
    return {row.system: row.state for row in application.provisioned_resources.all()}


# Coverage of the trigger set


def test_every_transition_that_can_strand_the_ledger_deprovisions():
    """Ledger rows only exist from PROVISIONING onward, so any move out of those
    states into a terminal one has to tear them down."""
    stranding = {
        (from_state, action)
        for (from_state, action), spec in ABDMWorkflow.transitions.items()
        if from_state
        in {
            ApplicationState.PROVISIONING_FAILED,
            ApplicationState.PROVISIONED,
        }
        and spec.to_state == ApplicationState.WITHDRAWN
    }
    for key in stranding:
        assert "deprovisioning_chain" in ABDMWorkflow.transitions[key].hooks


# Happy path


def test_withdrawal_after_provisioning_disables_all_three(
    application,
    owner,
    django_capture_on_commit_callbacks,
):
    _provision(application, owner, django_capture_on_commit_callbacks)
    assert application.state == ApplicationState.PROVISIONED

    with django_capture_on_commit_callbacks(execute=True):
        transition(application=application, action="WITHDRAW", actor=owner)

    assert set(_states(application).values()) == {ProvisionedResourceState.DISABLED}
    client = ProvisionedResource.objects.get(
        application=application,
        system=ProvisionedSystem.KEYCLOAK,
    )
    record = fakes.FakeIdpAdmin().get_client(client.external_ref)
    assert record is not None
    assert record["enabled"] is False


def test_the_bridge_and_the_subscription_go_too(
    application,
    owner,
    django_capture_on_commit_callbacks,
):
    """Legacy disabled the Keycloak client and left these two live for good."""
    _provision(application, owner, django_capture_on_commit_callbacks)
    wso2 = ProvisionedResource.objects.get(
        application=application,
        system=ProvisionedSystem.WSO2,
    )

    with django_capture_on_commit_callbacks(execute=True):
        transition(application=application, action="WITHDRAW", actor=owner)

    record = fakes.FakeApiGateway().get_application(wso2.external_ref)
    assert record is not None
    assert record["subscriptions"] == []
    bridge = ProvisionedResource.objects.get(
        application=application,
        system=ProvisionedSystem.HIECM,
    )
    status = fakes.FakeBridgeRegistry().get_bridge_status(bridge.external_ref)
    assert status.active is False


def test_rejecting_an_unprovisioned_application_is_a_no_op(
    application,
    owner,
    django_capture_on_commit_callbacks,
):
    """REJECT is only legal from SUBMITTED, where nothing has been created yet."""
    transition(application=application, action="SUBMIT", actor=owner)

    with django_capture_on_commit_callbacks(execute=True):
        transition(
            application=application,
            action="REJECT",
            actor=_staff("reject_application"),
        )

    assert application.provisioned_resources.count() == 0
    assert Message.objects.get().template_key == TemplateKey.SANDBOX_REJECTED


# The gap B8 found


def test_a_permanently_failed_application_can_be_withdrawn_and_cleaned_up(
    application,
    owner,
    django_capture_on_commit_callbacks,
):
    """Retry used to be the only move out of PROVISIONING_FAILED, which left the
    partial resources it did create switched on with no way to reach them."""
    fail_next(ExternalSystem.HIECM, "create_bridge", retryable=False)
    _provision(application, owner, django_capture_on_commit_callbacks)
    assert application.state == ApplicationState.PROVISIONING_FAILED

    with django_capture_on_commit_callbacks(execute=True):
        transition(application=application, action="WITHDRAW", actor=owner)

    application.refresh_from_db()
    assert application.state == ApplicationState.WITHDRAWN
    assert _states(application) == {
        ProvisionedSystem.KEYCLOAK: ProvisionedResourceState.DISABLED,
        ProvisionedSystem.WSO2: ProvisionedResourceState.DISABLED,
    }


# Idempotency and failure


def test_re_running_the_teardown_is_harmless(
    application,
    owner,
    django_capture_on_commit_callbacks,
):
    from sandbox.integrations.tasks import deprovision_keycloak  # noqa: PLC0415

    _provision(application, owner, django_capture_on_commit_callbacks)
    with django_capture_on_commit_callbacks(execute=True):
        transition(application=application, action="WITHDRAW", actor=owner)

    deprovision_keycloak.delay(application.pk, "cid")

    assert set(_states(application).values()) == {ProvisionedResourceState.DISABLED}


@override_settings(PROVISIONING_MAX_ATTEMPTS=1)
def test_one_failed_step_does_not_strand_the_others(
    application,
    owner,
    django_capture_on_commit_callbacks,
):
    """The opposite rule to provisioning: a resource left on is a live credential."""
    _provision(application, owner, django_capture_on_commit_callbacks)
    always_fail(ExternalSystem.KEYCLOAK, code="REALM_DOWN", retryable=True)

    with django_capture_on_commit_callbacks(execute=True):
        transition(application=application, action="WITHDRAW", actor=owner)

    assert _states(application) == {
        ProvisionedSystem.KEYCLOAK: ProvisionedResourceState.FAILED,
        ProvisionedSystem.WSO2: ProvisionedResourceState.DISABLED,
        ProvisionedSystem.HIECM: ProvisionedResourceState.DISABLED,
    }


@override_settings(PROVISIONING_MAX_ATTEMPTS=1)
def test_a_failed_teardown_is_retryable_from_the_console(
    application,
    owner,
    django_capture_on_commit_callbacks,
):
    _provision(application, owner, django_capture_on_commit_callbacks)
    always_fail(ExternalSystem.KEYCLOAK, code="REALM_DOWN", retryable=True)
    with django_capture_on_commit_callbacks(execute=True):
        transition(application=application, action="WITHDRAW", actor=owner)
    fakes.clear_failures(ExternalSystem.KEYCLOAK)

    with django_capture_on_commit_callbacks(execute=True):
        retry_deprovisioning(
            application=application,
            actor=_staff("retry_provisioning"),
        )

    assert set(_states(application).values()) == {ProvisionedResourceState.DISABLED}


def test_retrying_a_teardown_needs_the_permission(
    application,
    owner,
    django_capture_on_commit_callbacks,
):
    """No transition to inherit the check from, so it is made explicitly."""
    _provision(application, owner, django_capture_on_commit_callbacks)

    with pytest.raises(DomainError) as exc:
        retry_deprovisioning(application=application, actor=UserFactory.create())

    assert exc.value.code == "forbidden"


def test_a_console_retry_is_audited(
    application,
    owner,
    django_capture_on_commit_callbacks,
):
    _provision(application, owner, django_capture_on_commit_callbacks)

    with django_capture_on_commit_callbacks(execute=True):
        retry_deprovisioning(
            application=application,
            actor=_staff("retry_provisioning"),
        )

    assert AuditEvent.objects.filter(
        action="application.deprovisioning_retried",
        object_external_id=application.external_id,
    ).exists()
