"""The reverse chain, and what it refuses to leave switched on.

Teardown is driven here through `enqueue_teardown` on a genuinely provisioned
application, not through the action that should reach it. The registry has no
action that does: `reject` and `withdraw` both stop short of `approved`, so the
only application with a full ledger is one no action can revoke. Plan 12 §6's
`approved`-reachable action is what closes that, and until it lands these tests
cover the chain rather than the route to it.
"""

from __future__ import annotations

import pytest
from django.test import override_settings

from sandbox.experiences.services import perform_application_action
from sandbox.integrations import fakes
from sandbox.integrations.fakes import always_fail
from sandbox.integrations.fakes import fail_next
from sandbox.integrations.models import ProvisionedResource
from sandbox.integrations.models import ProvisionedResourceState
from sandbox.integrations.models import ProvisionedSystem
from sandbox.integrations.ports import ExternalSystem
from sandbox.integrations.selectors import teardown_is_incomplete
from sandbox.integrations.tasks import deprovision_keycloak
from sandbox.integrations.tasks import enqueue_teardown
from sandbox.notifications.models import Message
from sandbox.notifications.models import TemplateKey

pytestmark = pytest.mark.django_db


def _states(application) -> dict[str, str]:
    return {row.system: row.state for row in application.provisioned_resources.all()}


def _tear_down(application, callbacks) -> None:
    with callbacks(execute=True):
        enqueue_teardown(application)


# ── Happy path ───────────────────────────────────────────────────────────────


def test_teardown_disables_all_three(approve, django_capture_on_commit_callbacks):
    application = approve()

    _tear_down(application, django_capture_on_commit_callbacks)

    assert set(_states(application).values()) == {ProvisionedResourceState.DISABLED}
    client = ProvisionedResource.objects.get(
        application=application,
        system=ProvisionedSystem.KEYCLOAK,
    )
    record = fakes.FakeIdpAdmin().get_client(client.external_ref)
    assert record is not None
    assert record["enabled"] is False


def test_the_bridge_and_the_subscription_go_too(
    approve,
    django_capture_on_commit_callbacks,
):
    """Legacy disabled the Keycloak client and left these two live for good."""
    application = approve()
    wso2 = ProvisionedResource.objects.get(
        application=application,
        system=ProvisionedSystem.WSO2,
    )

    _tear_down(application, django_capture_on_commit_callbacks)

    record = fakes.FakeApiGateway().get_application(wso2.external_ref)
    assert record is not None
    assert record["subscriptions"] == []
    bridge = ProvisionedResource.objects.get(
        application=application,
        system=ProvisionedSystem.HIECM,
    )
    assert (
        fakes.FakeBridgeRegistry().get_bridge_status(bridge.external_ref).active
        is False
    )


def test_a_partially_provisioned_application_is_cleaned_up_too(
    approve,
    django_capture_on_commit_callbacks,
):
    """The gap the old workflow left: a chain that failed at the bridge still
    created a client and a gateway app, and retry was the only move out."""
    fail_next(ExternalSystem.HIECM, "create_bridge", retryable=False)
    application = approve()

    _tear_down(application, django_capture_on_commit_callbacks)

    assert _states(application) == {
        ProvisionedSystem.KEYCLOAK: ProvisionedResourceState.DISABLED,
        ProvisionedSystem.WSO2: ProvisionedResourceState.DISABLED,
    }


# ── Through the action ───────────────────────────────────────────────────────


def test_rejecting_an_unprovisioned_application_is_a_no_op(reject):
    """Reject is only reachable before approval, where nothing exists yet — so
    its teardown effect runs against an empty ledger and must stay quiet."""
    application = reject()

    assert application.provisioned_resources.count() == 0
    assert Message.objects.get(application=application).template_key == (
        TemplateKey.SANDBOX_REJECTED
    )


@override_settings(PROVISIONING_MAX_ATTEMPTS=1)
def test_a_failed_teardown_is_retryable_through_the_action(
    approve,
    reject,
    reviewer,
    django_capture_on_commit_callbacks,
):
    """The retry needs a rejected application to be offered on, which is what
    makes this the one teardown route an actor can actually take today."""
    application = approve()
    always_fail(ExternalSystem.KEYCLOAK, code="REALM_DOWN", retryable=True)
    _tear_down(application, django_capture_on_commit_callbacks)
    assert _states(application)[ProvisionedSystem.KEYCLOAK] == (
        ProvisionedResourceState.FAILED
    )

    fakes.clear_failures(ExternalSystem.KEYCLOAK)
    application.status = "rejected"
    application.save(update_fields=["status"])
    with django_capture_on_commit_callbacks(execute=True):
        perform_application_action(
            application=application,
            action_key="retry_deprovisioning",
            user=reviewer,
        )

    assert set(_states(application).values()) == {ProvisionedResourceState.DISABLED}
    assert not teardown_is_incomplete(application)


def test_the_retry_is_not_offered_once_nothing_is_left_on(
    approve,
    reviewer,
    django_capture_on_commit_callbacks,
):
    from sandbox.experiences.registry import registry  # noqa: PLC0415
    from sandbox.experiences.services import application_context  # noqa: PLC0415

    application = approve()
    _tear_down(application, django_capture_on_commit_callbacks)
    application.status = "rejected"
    application.save(update_fields=["status"])

    action = registry.get(application.application_type).get_action(
        "retry_deprovisioning",
    )
    available, reason = action.availability(
        application_context(application, reviewer),
    )

    assert available is False
    assert "still provisioned" in str(reason)


# ── Idempotency and failure ──────────────────────────────────────────────────


def test_re_running_the_teardown_is_harmless(
    approve,
    django_capture_on_commit_callbacks,
):
    application = approve()
    _tear_down(application, django_capture_on_commit_callbacks)

    deprovision_keycloak.delay(application.pk)

    assert set(_states(application).values()) == {ProvisionedResourceState.DISABLED}


@override_settings(PROVISIONING_MAX_ATTEMPTS=1)
def test_one_failed_step_does_not_strand_the_others(
    approve,
    django_capture_on_commit_callbacks,
):
    """The opposite rule to provisioning: a resource left on is a live credential,
    so a step that gives up must still let the next one run."""
    application = approve()
    always_fail(ExternalSystem.KEYCLOAK, code="REALM_DOWN", retryable=True)

    _tear_down(application, django_capture_on_commit_callbacks)

    assert _states(application) == {
        ProvisionedSystem.KEYCLOAK: ProvisionedResourceState.FAILED,
        ProvisionedSystem.WSO2: ProvisionedResourceState.DISABLED,
        ProvisionedSystem.HIECM: ProvisionedResourceState.DISABLED,
    }
