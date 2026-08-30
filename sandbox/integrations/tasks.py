"""The provisioning chain — Keycloak, then WSO2, then HIE-CM.

Order is forced by the data: WSO2 maps the Keycloak client's credentials as its
consumer key, and the bridge is named after that same client. Each step is
ledger-guarded, so a chain that dies half-way and is re-run finishes the missing
systems instead of creating a second set. Legacy ran all of this inline in the
approval request with no ledger, so a retry produced duplicate clients and
subscriptions, and a half-provisioned application still read as approved.

Every task takes the correlation id explicitly and rebinds it. `ContextVar` does
not survive `on_commit` → broker → worker, so without this the approval and the
provisioning it caused would carry different ids and could not be joined.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from celery import shared_task
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction

from sandbox.applications.models import Application
from sandbox.applications.models import ApplicationState
from sandbox.integrations.keycloak.roles import role_names_for
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
from sandbox.utils.correlation import get_correlation_id
from sandbox.utils.correlation import set_correlation_id
from sandbox.workflow.machine import Action
from sandbox.workflow.services import transition

if TYPE_CHECKING:
    from collections.abc import Callable

    from celery import Task

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
    application: Application,
    system: ProvisionedSystem,
) -> ProvisionedResource | None:
    return ProvisionedResource.objects.filter(
        application=application,
        system=system,
    ).first()


def _record(
    application: Application,
    system: ProvisionedSystem,
    *,
    external_ref: str,
    public_ref: str = "",
    secret_ref: str = "",
) -> ProvisionedResource:
    """Write the ledger the instant the external system says yes.

    The window between the remote create and this write is the one place a
    duplicate can still be born; P4's reconciliation sweep owns that residue.
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


def _fail(
    task: Task,
    application: Application,
    system: ProvisionedSystem,
    failure: _Failure,
) -> None:
    """Retry while it can plausibly help, then park the application visibly."""
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
    transition(
        application=application,
        action=Action.FAIL_PROVISIONING,
        comment=detail[: settings.PROVISIONING_DETAIL_MAX_CHARS],
        data={"system": str(system), "code": failure.code, "attempts": attempts},
    )


def _step(
    task: Task,
    application_id: int,
    correlation_id: str,
    system: ProvisionedSystem,
    run: Callable[[Application], None],
) -> int:
    """Shared shape of every step: rebind, skip if done, call, record, or park.

    `ImproperlyConfigured` is caught alongside the adapter errors on purpose — a
    missing API-name list is not a transient fault, and retrying it five times
    over half an hour only delays the operator finding out.
    """
    set_correlation_id(correlation_id)
    application = Application.objects.get(pk=application_id)

    # An earlier link already parked this run; later links must not carry on.
    if application.state != ApplicationState.PROVISIONING:
        return application_id

    row = _ledger_row(application, system)
    if row is not None and row.state == ProvisionedResourceState.ACTIVE:
        return application_id

    try:
        run(application)
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
def provision_keycloak(task: Task, application_id: int, correlation_id: str) -> int:
    """First link, so it is also what moves the application into PROVISIONING."""
    set_correlation_id(correlation_id)
    application = Application.objects.get(pk=application_id)

    # A retry arrives already in PROVISIONING, having been moved there by the
    # console's RETRY_PROVISIONING; only a fresh approval needs this move.
    if application.state == ApplicationState.SANDBOX_APPROVED:
        transition(application=application, action=Action.START_PROVISIONING)

    def run(application: Application) -> None:
        created = get_idp_admin().create_client(
            ClientSpec(
                reference=application.reference,
                display_name=application.product.name,
                role_names=role_names_for(application.kind),
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

    return _step(
        task,
        application_id,
        correlation_id,
        ProvisionedSystem.KEYCLOAK,
        run,
    )


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
def provision_wso2(task: Task, application_id: int, correlation_id: str) -> int:
    def run(application: Application) -> None:
        client = _ledger_row(application, ProvisionedSystem.KEYCLOAK)
        if client is None:
            message = "WSO2 needs the Keycloak client that should already exist"
            raise ImproperlyConfigured(message)

        api_names = api_names_for(application.kind)
        gateway = get_api_gateway()
        created = gateway.create_application(
            GatewayAppSpec(
                reference=application.reference,
                name=application.product.name,
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

    return _step(task, application_id, correlation_id, ProvisionedSystem.WSO2, run)


@shared_task(bind=True, max_retries=None)
def provision_hiecm(task: Task, application_id: int, correlation_id: str) -> int:
    def run(application: Application) -> None:
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
                name=application.product.name,
                url=_callback_url(application),
            ),
        )
        _record(
            application,
            ProvisionedSystem.HIECM,
            external_ref=bridge_id,
            public_ref=bridge_id,
        )

    return _step(task, application_id, correlation_id, ProvisionedSystem.HIECM, run)


@shared_task
def complete_provisioning(application_id: int, correlation_id: str) -> int:
    """Only the ledger decides this — never "the chain got this far"."""
    set_correlation_id(correlation_id)
    application = Application.objects.get(pk=application_id)

    if application.state != ApplicationState.PROVISIONING:
        return application_id

    done = set(
        ProvisionedResource.objects.filter(
            application=application,
            state=ProvisionedResourceState.ACTIVE,
        ).values_list("system", flat=True),
    )
    missing = set(ProvisionedSystem.values) - done
    if missing:
        logger.error(
            "provisioning for %s reached completion missing %s",
            application.reference,
            sorted(missing),
        )
        transition(
            application=application,
            action=Action.FAIL_PROVISIONING,
            comment=f"incomplete ledger: missing {', '.join(sorted(missing))}",
            data={"missing": sorted(missing)},
        )
        return application_id

    # PROVISIONED fires B6's `notify_provisioned`, which mails the panel link.
    transition(application=application, action=Action.COMPLETE_PROVISIONING)
    return application_id


def _callback_url(application: Application) -> str:
    """Where HIE-CM delivers this integrator's gateway callbacks.

    A per-application placeholder until P4's `applications_callback` collects the
    integrator's real endpoint. Legacy pointed *every* bridge at one hardcoded
    webhook.site bin, so one public request bin received every integrator's
    callbacks; whatever this base is, it must at least be ours.
    """
    base = settings.HIECM_BRIDGE_CALLBACK_BASE_URL.rstrip("/")
    return f"{base}/{application.external_id}"


def enqueue_chain(application: Application) -> None:
    """Schedule the whole chain for after the caller's transaction commits."""
    application_id = application.pk
    correlation_id = get_correlation_id()

    def _send() -> None:
        (
            provision_keycloak.s(application_id, correlation_id)
            | provision_wso2.s(correlation_id)
            | provision_hiecm.s(correlation_id)
            | complete_provisioning.s(correlation_id)
        ).delay()

    transaction.on_commit(_send)
