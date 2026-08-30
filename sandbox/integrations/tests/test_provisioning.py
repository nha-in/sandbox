"""B7 acceptance criteria — the chain, the ledger, and what a retry does."""

from __future__ import annotations

import pytest
from celery.exceptions import Retry
from django.contrib.auth.models import Permission
from django.test import override_settings

from sandbox.applications.models import ApplicationState
from sandbox.applications.tests.factories import ApplicationFactory
from sandbox.audit.models import AuditEvent
from sandbox.integrations.credentials import take_initial_secret
from sandbox.integrations.fakes import always_fail
from sandbox.integrations.fakes import fail_next
from sandbox.integrations.hooks import register_workflow_hooks
from sandbox.integrations.models import ProvisionedResource
from sandbox.integrations.models import ProvisionedResourceState
from sandbox.integrations.models import ProvisionedSystem
from sandbox.integrations.ports import ExternalSystem
from sandbox.integrations.secret_ref import discard_secret
from sandbox.integrations.secret_ref import resolve_secret
from sandbox.integrations.services import retry_provisioning
from sandbox.notifications import hooks as notification_hooks
from sandbox.notifications.models import Message
from sandbox.notifications.models import TemplateKey
from sandbox.organisations.tests.factories import MembershipFactory
from sandbox.users.models import User
from sandbox.users.tests.factories import UserFactory
from sandbox.utils.correlation import set_correlation_id
from sandbox.workflow import services as workflow_services
from sandbox.workflow.machine import Action
from sandbox.workflow.services import transition

pytestmark = pytest.mark.django_db

ALL_SYSTEMS = set(ProvisionedSystem.values)


@pytest.fixture(autouse=True)
def _hooks():
    """Other suites call `clear_hooks()`, which wipes what `ready()` registered."""
    workflow_services.clear_hooks()
    register_workflow_hooks()
    notification_hooks.register_workflow_hooks()
    yield
    workflow_services.clear_hooks()


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


def _approve(application, owner, callbacks) -> None:
    """Approve, running the on-commit chain the approval schedules."""
    transition(application=application, action=Action.SUBMIT, actor=owner)
    approver = _staff("approve_application")
    with callbacks(execute=True):
        transition(application=application, action=Action.APPROVE, actor=approver)
    application.refresh_from_db()


def _systems(application) -> set[str]:
    return set(
        ProvisionedResource.objects.filter(
            application=application,
            state=ProvisionedResourceState.ACTIVE,
        ).values_list("system", flat=True),
    )


def _refs(application) -> dict[int, str]:
    return {row.pk: row.external_ref for row in application.provisioned_resources.all()}


# Happy path


def test_approval_provisions_all_three_systems_and_lands_provisioned(
    application,
    owner,
    django_capture_on_commit_callbacks,
):
    _approve(application, owner, django_capture_on_commit_callbacks)

    assert application.state == ApplicationState.PROVISIONED
    assert _systems(application) == ALL_SYSTEMS


def test_completion_sends_the_approval_email(
    application,
    owner,
    django_capture_on_commit_callbacks,
):
    _approve(application, owner, django_capture_on_commit_callbacks)

    message = Message.objects.get(template_key=TemplateKey.SANDBOX_APPROVED)
    assert message.recipient == application.applicant.email


def test_the_keycloak_row_carries_both_references(
    application,
    owner,
    django_capture_on_commit_callbacks,
):
    """`external_ref` is what B8 disables; `public_ref` is what C7 displays."""
    _approve(application, owner, django_capture_on_commit_callbacks)

    row = ProvisionedResource.objects.get(
        application=application,
        system=ProvisionedSystem.KEYCLOAK,
    )
    assert row.external_ref
    assert row.public_ref.startswith("SBX_")
    assert row.external_ref != row.public_ref


def test_the_bridge_is_named_after_the_client(
    application,
    owner,
    django_capture_on_commit_callbacks,
):
    _approve(application, owner, django_capture_on_commit_callbacks)

    rows = {row.system: row for row in application.provisioned_resources.all()}
    assert (
        rows[ProvisionedSystem.HIECM].external_ref
        == rows[ProvisionedSystem.KEYCLOAK].public_ref
    )


# Idempotency


def test_re_running_the_chain_creates_nothing_new(
    application,
    owner,
    django_capture_on_commit_callbacks,
):
    """The kill-and-retry property, expressed as "run it twice"."""
    _approve(application, owner, django_capture_on_commit_callbacks)
    before = _refs(application)

    from sandbox.integrations.tasks import provision_keycloak  # noqa: PLC0415

    provision_keycloak.delay(application.pk, "cid")

    assert _refs(application) == before


def test_a_retry_provisions_only_the_missing_system(
    application,
    owner,
    django_capture_on_commit_callbacks,
):
    fail_next(ExternalSystem.HIECM, "create_bridge", retryable=False)
    _approve(application, owner, django_capture_on_commit_callbacks)

    assert application.state == ApplicationState.PROVISIONING_FAILED
    assert _systems(application) == {
        ProvisionedSystem.KEYCLOAK,
        ProvisionedSystem.WSO2,
    }
    keycloak_before = ProvisionedResource.objects.get(
        application=application,
        system=ProvisionedSystem.KEYCLOAK,
    ).external_ref

    with django_capture_on_commit_callbacks(execute=True):
        retry_provisioning(
            application=application,
            actor=_staff("retry_provisioning"),
        )

    application.refresh_from_db()
    assert application.state == ApplicationState.PROVISIONED
    assert _systems(application) == ALL_SYSTEMS
    assert (
        ProvisionedResource.objects.get(
            application=application,
            system=ProvisionedSystem.KEYCLOAK,
        ).external_ref
        == keycloak_before
    )


# Failure


@override_settings(PROVISIONING_MAX_ATTEMPTS=1)
def test_a_failing_step_parks_the_application_with_the_reason(
    application,
    owner,
    django_capture_on_commit_callbacks,
):
    always_fail(ExternalSystem.KEYCLOAK, code="REALM_DOWN", retryable=True)

    _approve(application, owner, django_capture_on_commit_callbacks)

    assert application.state == ApplicationState.PROVISIONING_FAILED
    record = application.transitions.first()
    assert "REALM_DOWN" in record.comment
    assert "KEYCLOAK" in record.comment


def test_a_failed_step_stops_the_rest_of_the_chain(
    application,
    owner,
    django_capture_on_commit_callbacks,
):
    fail_next(ExternalSystem.KEYCLOAK, "create_client", retryable=False)

    _approve(application, owner, django_capture_on_commit_callbacks)

    assert application.state == ApplicationState.PROVISIONING_FAILED
    assert _systems(application) == set()


def test_a_retryable_failure_retries_instead_of_parking(
    application,
    owner,
    django_capture_on_commit_callbacks,
):
    from sandbox.integrations.tasks import provision_keycloak  # noqa: PLC0415

    transition(application=application, action=Action.SUBMIT, actor=owner)
    transition(
        application=application,
        action=Action.APPROVE,
        actor=_staff("approve_application"),
    )
    transition(application=application, action=Action.START_PROVISIONING)
    always_fail(ExternalSystem.KEYCLOAK, code="REALM_DOWN", retryable=True)

    with pytest.raises(Retry):
        provision_keycloak.delay(application.pk, "cid")

    application.refresh_from_db()
    assert application.state == ApplicationState.PROVISIONING


def test_backoff_doubles_and_is_capped():
    from sandbox.integrations.tasks import _backoff  # noqa: PLC0415

    with override_settings(
        PROVISIONING_RETRY_BACKOFF_SECONDS=120,
        PROVISIONING_RETRY_BACKOFF_MAX_SECONDS=900,
    ):
        assert [_backoff(n) for n in range(4)] == [120, 240, 480, 900]


def test_a_missing_api_name_list_fails_without_retrying(
    application,
    owner,
    django_capture_on_commit_callbacks,
):
    """Configuration is not a transient fault, so it must not burn five attempts."""
    with override_settings(WSO2_API_NAMES={"SANDBOX": ()}):
        _approve(application, owner, django_capture_on_commit_callbacks)

    assert application.state == ApplicationState.PROVISIONING_FAILED
    assert _systems(application) == {ProvisionedSystem.KEYCLOAK}
    assert "CONFIG_ERROR" in application.transitions.first().comment


def test_completion_refuses_an_incomplete_ledger(
    application,
    owner,
    django_capture_on_commit_callbacks,
):
    """`PROVISIONED` is a claim about three systems, not about the chain running."""
    from sandbox.integrations.tasks import complete_provisioning  # noqa: PLC0415

    transition(application=application, action=Action.SUBMIT, actor=owner)
    transition(
        application=application,
        action=Action.APPROVE,
        actor=_staff("approve_application"),
    )
    transition(application=application, action=Action.START_PROVISIONING)

    complete_provisioning.delay(application.pk, "cid")

    application.refresh_from_db()
    assert application.state == ApplicationState.PROVISIONING_FAILED


# Secrets


def test_no_secret_is_persisted_anywhere(
    application,
    owner,
    django_capture_on_commit_callbacks,
):
    _approve(application, owner, django_capture_on_commit_callbacks)

    row = ProvisionedResource.objects.get(
        application=application,
        system=ProvisionedSystem.KEYCLOAK,
    )
    secret = resolve_secret(row.secret_ref, ExternalSystem.KEYCLOAK)
    assert secret
    # The ref is a cache key; the value must appear in no column of any row.
    stored = " ".join(
        f"{r.external_ref}{r.public_ref}{r.secret_ref}"
        for r in ProvisionedResource.objects.all()
    )
    assert secret not in stored


def test_the_initial_secret_can_be_read_exactly_once(
    application,
    owner,
    django_capture_on_commit_callbacks,
):
    _approve(application, owner, django_capture_on_commit_callbacks)

    assert take_initial_secret(application)
    assert take_initial_secret(application) is None


def test_an_expired_parked_secret_is_re_minted_rather_than_dead_ending(
    application,
    owner,
):
    """`SECRET_REF_TTL_SECONDS` is shorter than this chain's own retry budget.

    Without rotation, a WSO2 outage outlasting the TTL reaches a step that can
    never succeed: Keycloak is already ACTIVE so it is skipped, and nothing else
    mints a replacement secret.
    """
    from sandbox.integrations.tasks import provision_keycloak  # noqa: PLC0415
    from sandbox.integrations.tasks import provision_wso2  # noqa: PLC0415

    transition(application=application, action=Action.SUBMIT, actor=owner)
    transition(
        application=application,
        action=Action.APPROVE,
        actor=_staff("approve_application"),
    )
    transition(application=application, action=Action.START_PROVISIONING)
    provision_keycloak.delay(application.pk, "cid")

    row = ProvisionedResource.objects.get(
        application=application,
        system=ProvisionedSystem.KEYCLOAK,
    )
    expired_ref = row.secret_ref
    stale_secret = resolve_secret(expired_ref, ExternalSystem.KEYCLOAK)
    discard_secret(expired_ref)

    provision_wso2.delay(application.pk, "cid")

    row.refresh_from_db()
    assert row.secret_ref != expired_ref
    # A new ref alone would still pass if we had re-parked the same value, which
    # would leave WSO2 holding a secret Keycloak no longer honours.
    assert resolve_secret(row.secret_ref, ExternalSystem.KEYCLOAK) != stale_secret
    assert ProvisionedSystem.WSO2 in _systems(application)


# Correlation


def test_one_correlation_id_spans_approval_and_provisioning(
    application,
    owner,
    django_capture_on_commit_callbacks,
):
    """The id must survive on_commit → broker → worker, which a ContextVar cannot."""
    set_correlation_id("b7b7b7b7b7b7b7b7b7b7b7b7b7b7b7b7")

    _approve(application, owner, django_capture_on_commit_callbacks)

    ids = set(
        AuditEvent.objects.filter(
            object_external_id=application.external_id,
        ).values_list("correlation_id", flat=True),
    )
    assert ids == {"b7b7b7b7b7b7b7b7b7b7b7b7b7b7b7b7"}


def test_every_state_move_is_audited(
    application,
    owner,
    django_capture_on_commit_callbacks,
):
    _approve(application, owner, django_capture_on_commit_callbacks)

    actions = list(
        application.transitions.order_by("created_date").values_list(
            "action",
            flat=True,
        ),
    )
    assert actions == [
        Action.SUBMIT,
        Action.APPROVE,
        Action.START_PROVISIONING,
        Action.COMPLETE_PROVISIONING,
    ]
