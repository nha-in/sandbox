"""The provisioning chain — Keycloak, then WSO2, then HIE-CM.

Order is forced by the data: WSO2 maps the Keycloak client's credentials as its
consumer key, and the bridge is named after that same client. Each step is
ledger-guarded, so a chain that dies half-way and is re-run finishes the missing
systems instead of creating a second set. Legacy ran all of this inline in the
approval request with no ledger, so a retry produced duplicate clients and
subscriptions, and a half-provisioned application still read as approved.

The correlation id travels as a message header, bound before every task body
by `config.celery_app`. A `ContextVar` does not survive `on_commit` → broker →
worker, so it has to cross as data — but as a header rather than an argument,
which is what stops a task from being written that quietly forgets to carry it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from celery import shared_task
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.utils import timezone

from sandbox.experiences.models import ApplicationInstance
from sandbox.integrations.events import record
from sandbox.integrations.keycloak.roles import role_names_for
from sandbox.integrations.models import TEARDOWN_PENDING_STATES
from sandbox.integrations.models import ProvisionedResource
from sandbox.integrations.models import ProvisionedResourceState
from sandbox.integrations.models import ProvisionedSystem
from sandbox.integrations.ports import AdapterError
from sandbox.integrations.ports import BridgeSpec
from sandbox.integrations.ports import ClientSpec
from sandbox.integrations.ports import GatewayAppSpec
from sandbox.integrations.registry import get_api_gateway
from sandbox.integrations.registry import get_bridge_registry
from sandbox.integrations.registry import get_idp_admin
from sandbox.integrations.secret_ref import has_secret
from sandbox.integrations.secret_ref import store_secret
from sandbox.integrations.wso2.apis import api_names_for
from sandbox.notifications.hooks import send
from sandbox.notifications.models import TemplateKey
from sandbox.organisations.models import ProvisioningRun
from sandbox.utils.correlation import get_correlation_id

if TYPE_CHECKING:
    from collections.abc import Callable

    from celery import Task
    from django.contrib.auth.models import AbstractBaseUser

logger = logging.getLogger(__name__)

CONFIG_ERROR = "CONFIG_ERROR"


@dataclass(frozen=True, slots=True)
class _Failure:
    code: str
    detail: str
    retryable: bool


def _backoff(retries: int) -> float:
    delay = settings.PROVISIONING_RETRY_BACKOFF_SECONDS * (2**retries)
    return min(delay, settings.PROVISIONING_RETRY_BACKOFF_MAX_SECONDS)


def _ledger_row(
    application: ApplicationInstance,
    system: ProvisionedSystem,
) -> ProvisionedResource | None:
    return ProvisionedResource.objects.filter(
        application=application,
        system=system,
    ).first()


def _record(
    application: ApplicationInstance,
    system: ProvisionedSystem,
    *,
    external_ref: str,
    public_ref: str = "",
    secret_ref: str = "",
) -> ProvisionedResource:
    """Write the ledger the instant the external system says yes.

    The gap between the remote create and this write only orphans a Keycloak
    client: WSO2 create-or-looks-up and HIE-CM upserts, but a random client id
    dies with the task that made it. P4's reconciliation sweep owns that.
    """
    row, _created = ProvisionedResource.objects.update_or_create(
        application=application,
        system=system,
        defaults={
            "external_ref": external_ref,
            "public_ref": public_ref,
            "secret_ref": secret_ref,
            "state": ProvisionedResourceState.ACTIVE,
        },
    )
    return row


def _open_run(application: ApplicationInstance) -> ProvisioningRun | None:
    """The attempt this application is currently in the middle of, if any."""
    return (
        ProvisioningRun.objects.filter(
            application=application,
            status=ProvisioningRun.Status.RUNNING,
        )
        .order_by("-started_at")
        .first()
    )


def _close_run(application: ApplicationInstance, status: str, error: str = "") -> None:
    """Finish the newest open attempt for this application, if there is one."""
    run = _open_run(application)
    if run is None:
        return
    run.status = status
    run.error = error
    run.finished_at = timezone.now()
    run.save(update_fields=["status", "error", "finished_at", "modified_at"])


def _fail(
    task: Task,
    application: ApplicationInstance,
    system: ProvisionedSystem,
    failure: _Failure,
) -> None:
    """Retry while it can plausibly help, then close the attempt with the reason.

    The reason is the whole point of closing it here rather than leaving it to
    `complete_provisioning`, which can only see *that* the ledger is short.
    """
    attempts = task.request.retries + 1
    if failure.retryable and attempts < settings.PROVISIONING_MAX_ATTEMPTS:
        raise task.retry(countdown=_backoff(task.request.retries))

    # No row is written for a system that produced nothing: absence already
    # means "not provisioned", and a phantom row with an empty ref would have to
    # be reasoned about by every reader of the ledger.
    row = _ledger_row(application, system)
    if row is not None:
        row.state = ProvisionedResourceState.FAILED
        row.save(update_fields=["state", "modified_date"])

    detail = f"{system}/{failure.code}: {failure.detail}"
    # ERROR, so it reaches Sentry through the logging integration (production.py).
    logger.error("provisioning failed for %s: %s", application.reference, detail)
    _close_run(application, ProvisioningRun.Status.FAILED, detail)
    record(
        "provisioning.failed",
        application=application,
        title="Provisioning failed",
        payload={
            "system": str(system),
            "code": failure.code,
            "attempts": attempts,
            "detail": detail[: settings.PROVISIONING_DETAIL_MAX_CHARS],
        },
    )


def _step(
    task: Task,
    application_id: int,
    system: ProvisionedSystem,
    call: Callable[[ApplicationInstance], None],
) -> int:
    """Shared shape of every step: skip what is settled, call, or fail.

    `ImproperlyConfigured` is caught alongside the adapter errors on purpose — a
    missing API-name list is not a transient fault, and retrying it five times
    over half an hour only delays the operator finding out.
    """
    application = ApplicationInstance.objects.get(pk=application_id)

    # An earlier link already closed this attempt; later links must not carry
    # on. Without this a WSO2 failure still builds a bridge for a client with no
    # gateway subscription behind it — the guard the deleted PROVISIONING state
    # used to provide. An application with no attempt record at all is not
    # stopped: that is a task invoked directly, which has nothing to abandon.
    if application.provisioning_runs.exists() and _open_run(application) is None:
        return application_id

    # This system is already done — the whole of what makes a retry safe.
    row = _ledger_row(application, system)
    if row is not None and row.state == ProvisionedResourceState.ACTIVE:
        return application_id

    try:
        call(application)
    except AdapterError as error:
        _fail(
            task,
            application,
            system,
            _Failure(error.code, error.message, retryable=error.retryable),
        )
    except ImproperlyConfigured as error:
        _fail(
            task,
            application,
            system,
            _Failure(CONFIG_ERROR, str(error), retryable=False),
        )

    return application_id


@shared_task(bind=True, max_retries=None)
def provision_keycloak(task: Task, application_id: int) -> int:
    """First link in the chain: the client every later step is named after."""

    def run(application: ApplicationInstance) -> None:
        created = get_idp_admin().create_client(
            ClientSpec(
                reference=application.reference,
                display_name=application.organisation.display_name,
                role_names=role_names_for(application.application_type),
            ),
        )
        _record(
            application,
            ProvisionedSystem.KEYCLOAK,
            external_ref=created.external_id,
            public_ref=created.client_id,
            # Parked, never persisted: C7 reads it once and the TTL clears it.
            secret_ref=store_secret(created.initial_secret),
        )

    return _step(task, application_id, ProvisionedSystem.KEYCLOAK, run)


def _live_secret_ref(client: ProvisionedResource) -> str:
    """The parked secret, re-minted if it aged out while WSO2 was unreachable.

    `SECRET_REF_TTL_SECONDS` is deliberately short, and shorter than this chain's
    own retry budget: a WSO2 outage lasting past the TTL would otherwise reach a
    step that can never succeed, since the Keycloak row is already ACTIVE and
    nothing would mint a replacement. Rotation is the way back, and it is what
    `external_ref` is held for.
    """
    if has_secret(client.secret_ref):
        return client.secret_ref

    rotated = get_idp_admin().rotate_client_secret(client.external_ref)
    client.secret_ref = store_secret(rotated.secret)
    client.save(update_fields=["secret_ref", "modified_date"])
    return client.secret_ref


@shared_task(bind=True, max_retries=None)
def provision_wso2(task: Task, application_id: int) -> int:
    def run(application: ApplicationInstance) -> None:
        client = _ledger_row(application, ProvisionedSystem.KEYCLOAK)
        if client is None:
            message = "WSO2 needs the Keycloak client that should already exist"
            raise ImproperlyConfigured(message)

        api_names = api_names_for(application.application_type)
        gateway = get_api_gateway()
        created = gateway.create_application(
            GatewayAppSpec(
                reference=application.reference,
                name=application.organisation.display_name,
                api_names=api_names,
            ),
        )
        gateway.subscribe(created.external_id, api_names)
        gateway.map_keys(
            created.external_id,
            consumer_key=client.public_ref,
            secret_ref=_live_secret_ref(client),
        )
        _record(
            application,
            ProvisionedSystem.WSO2,
            external_ref=created.external_id,
            public_ref=created.name,
        )

    return _step(task, application_id, ProvisionedSystem.WSO2, run)


@shared_task(bind=True, max_retries=None)
def provision_hiecm(task: Task, application_id: int) -> int:
    def run(application: ApplicationInstance) -> None:
        client = _ledger_row(application, ProvisionedSystem.KEYCLOAK)
        if client is None:
            message = "the bridge is named after a Keycloak client that is missing"
            raise ImproperlyConfigured(message)

        # Named after the client, as legacy did — but from a random client id
        # rather than legacy's guessable `SBXID_(sdId + 55)`.
        bridge_id = client.public_ref
        get_bridge_registry().create_bridge(
            BridgeSpec(
                bridge_id=bridge_id,
                name=application.organisation.display_name,
                url=_callback_url(application),
            ),
        )
        _record(
            application,
            ProvisionedSystem.HIECM,
            external_ref=bridge_id,
            public_ref=bridge_id,
        )

    return _step(task, application_id, ProvisionedSystem.HIECM, run)


@shared_task
def complete_provisioning(application_id: int) -> int:
    """Only the ledger decides this — never "the chain got this far"."""
    application = ApplicationInstance.objects.get(pk=application_id)

    done = set(
        ProvisionedResource.objects.filter(
            application=application,
            state=ProvisionedResourceState.ACTIVE,
        ).values_list("system", flat=True),
    )
    missing = set(ProvisionedSystem.values) - done
    if missing:
        # Usually a step already failed, closed the attempt with the reason the
        # adapter gave, and logged it — that reason is better than anything
        # derivable here, so say nothing rather than record the same failure
        # twice under a vaguer name. An attempt still open means the ledger is
        # short with nothing to blame, which is the case worth shouting about.
        if _open_run(application) is not None:
            logger.error(
                "provisioning for %s reached completion missing %s",
                application.reference,
                sorted(missing),
            )
            _close_run(
                application,
                ProvisioningRun.Status.FAILED,
                f"incomplete ledger: missing {', '.join(sorted(missing))}",
            )
            record(
                "provisioning.failed",
                application=application,
                title="Provisioning incomplete",
                payload={"missing": sorted(missing)},
            )
        return application_id

    record(
        "provisioning.completed",
        application=application,
        title="Provisioning completed",
        payload={"systems": sorted(done)},
    )
    _close_run(application, ProvisioningRun.Status.READY)
    # Sent from here, not from an action: nobody performed this.
    send(TemplateKey.SANDBOX_APPROVED, application)
    return application_id


def _callback_url(application: ApplicationInstance) -> str:
    """Where HIE-CM delivers this integrator's gateway callbacks.

    A per-application placeholder until P4's `applications_callback` collects the
    integrator's real endpoint. Legacy pointed *every* bridge at one hardcoded
    webhook.site bin, so one public request bin received every integrator's
    callbacks; whatever this base is, it must at least be ours.
    """
    base = settings.HIECM_BRIDGE_CALLBACK_BASE_URL.rstrip("/")
    return f"{base}/{application.reference}"


def enqueue_chain(
    application: ApplicationInstance,
    started_by: AbstractBaseUser | None = None,
) -> None:
    """Schedule the whole chain for after the caller's transaction commits.

    Opens the attempt record first, so a run that dies before any adapter
    returns still leaves a row saying it was tried.
    """
    application_id = application.pk
    correlation_id = get_correlation_id()
    ProvisioningRun.objects.create(
        application=application,
        correlation_id=correlation_id or "",
        started_by=started_by,
    )

    def _send() -> None:
        # `.si`, not `.s`: an immutable signature ignores the previous task's
        # return value, so each link states the application it is for instead
        # of inheriting it. With `.s` the chain only holds together because
        # every exit path in `_step` happens to `return application_id`, and a
        # link that returned anything else would hand the next one a bad pk.
        (
            provision_keycloak.si(application_id)
            | provision_wso2.si(application_id)
            | provision_hiecm.si(application_id)
            | complete_provisioning.si(application_id)
        ).delay()

    transaction.on_commit(_send)


# Teardown — B8


def _teardown_failed(
    task: Task,
    row: ProvisionedResource,
    failure: _Failure,
) -> None:
    """Mark this one resource failed. Deliberately does not raise.

    Provisioning stops at the first failure because there is no point building a
    bridge for a client that does not exist. Teardown is the opposite: every
    resource left switched on is a live credential for a rejected integrator, so
    a step that gives up must still let the next one run.
    """
    attempts = task.request.retries + 1
    if failure.retryable and attempts < settings.PROVISIONING_MAX_ATTEMPTS:
        raise task.retry(countdown=_backoff(task.request.retries))

    row.state = ProvisionedResourceState.FAILED
    row.save(update_fields=["state", "modified_date"])
    # ERROR reaches Sentry through the logging integration (production.py).
    logger.error(
        "deprovisioning %s for application %s failed after %s attempts: %s: %s",
        row.system,
        row.application_id,
        attempts,
        failure.code,
        failure.detail,
    )


def _teardown_step(
    task: Task,
    application_id: int,
    system: ProvisionedSystem,
    call: Callable[[ApplicationInstance, ProvisionedResource], None],
) -> int:
    application = ApplicationInstance.objects.get(pk=application_id)

    # Missing means nothing was ever created and DISABLED means a previous run
    # finished the job; both are success. FAILED is not — that is a resource we
    # tried and failed to switch off, and it is precisely what a retry is for.
    row = _ledger_row(application, system)
    if row is None or row.state not in TEARDOWN_PENDING_STATES:
        return application_id

    try:
        call(application, row)
    except AdapterError as error:
        _teardown_failed(
            task,
            row,
            _Failure(error.code, error.message, retryable=error.retryable),
        )
        return application_id
    except ImproperlyConfigured as error:
        _teardown_failed(task, row, _Failure(CONFIG_ERROR, str(error), retryable=False))
        return application_id

    row.state = ProvisionedResourceState.DISABLED
    row.save(update_fields=["state", "modified_date"])
    return application_id


@shared_task(bind=True, max_retries=None)
def deprovision_keycloak(task: Task, application_id: int) -> int:
    """First, because it is the only step that actually stops token issuance."""

    def run(_application: ApplicationInstance, row: ProvisionedResource) -> None:
        get_idp_admin().disable_client(row.external_ref)

    return _teardown_step(task, application_id, ProvisionedSystem.KEYCLOAK, run)


@shared_task(bind=True, max_retries=None)
def deprovision_wso2(task: Task, application_id: int) -> int:
    def run(application: ApplicationInstance, row: ProvisionedResource) -> None:
        # The same source provisioning subscribed from. If the configured set has
        # changed since, the difference is left behind for P4's sweep rather than
        # guessed at from here.
        get_api_gateway().unsubscribe(
            row.external_ref,
            api_names_for(application.application_type),
        )

    return _teardown_step(task, application_id, ProvisionedSystem.WSO2, run)


@shared_task(bind=True, max_retries=None)
def deprovision_hiecm(task: Task, application_id: int) -> int:
    def run(_application: ApplicationInstance, row: ProvisionedResource) -> None:
        get_bridge_registry().deactivate_bridge(row.external_ref)

    return _teardown_step(task, application_id, ProvisionedSystem.HIECM, run)


def enqueue_teardown(application: ApplicationInstance) -> None:
    """Schedule the reverse chain for after the caller's transaction commits."""
    application_id = application.pk

    def _send() -> None:
        (
            deprovision_keycloak.si(application_id)
            | deprovision_wso2.si(application_id)
            | deprovision_hiecm.si(application_id)
        ).delay()

    transaction.on_commit(_send)
