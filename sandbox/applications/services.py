"""Application services — the only writers of Application rows."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from django.db import transaction
from django.utils import timezone

from sandbox.applications.models import Application
from sandbox.applications.models import ApplicationKind
from sandbox.applications.models import ApplicationReferenceCounter
from sandbox.applications.models import ApplicationState
from sandbox.applications.schemas import validate_payload
from sandbox.organisations.services import create_product
from sandbox.utils.errors import DomainError

if TYPE_CHECKING:
    from sandbox.organisations.models import Organisation
    from sandbox.organisations.models import Product
    from sandbox.users.models import User

_EDITABLE_STATES = (ApplicationState.DRAFT, ApplicationState.SENT_BACK)
_SCHEMA_VERSION = 1


def _next_reference() -> str:
    """Race-safe: unique `year` settles the create race, `select_for_update`
    serializes the increments."""
    year = timezone.now().year
    with transaction.atomic():
        counter, _created = (
            ApplicationReferenceCounter.objects.select_for_update().get_or_create(
                year=year,
            )
        )
        counter.last_value += 1
        counter.save(update_fields=["last_value"])
        return f"SBX-{year}-{counter.last_value:05d}"


@transaction.atomic
def create_draft(
    *,
    organisation: Organisation,
    product: Product,
    applicant: User,
    kind: str,
    data: dict[str, Any],
) -> Application:
    if kind != ApplicationKind.SANDBOX:
        message = f"{kind} enrollment is not available yet"
        raise DomainError(message)

    if product.organisation_id != organisation.pk:
        message = "product does not belong to this organisation"
        raise DomainError(message)

    payload = {"schema_version": _SCHEMA_VERSION, "data": data}
    validate_payload(kind, payload)
    return Application.objects.create(
        reference=_next_reference(),
        kind=kind,
        product=product,
        applicant=applicant,
        payload=payload,
    )


@transaction.atomic
def create_draft_with_new_product(
    *,
    organisation: Organisation,
    product_name: str,
    applicant: User,
    kind: str,
    data: dict[str, Any],
) -> Application:
    """C4 offers "pick a product or name a new one" in one form; the nested
    atomic block means a rejected payload rolls the new product back too."""
    return create_draft(
        organisation=organisation,
        product=create_product(organisation=organisation, name=product_name),
        applicant=applicant,
        kind=kind,
        data=data,
    )


@transaction.atomic
def update_draft(*, application: Application, data: dict[str, Any]) -> Application:
    if application.state not in _EDITABLE_STATES:
        message = f"cannot edit an application in state {application.state}"
        raise DomainError(message)

    # .get() so a missing key fails closed as DomainError, not KeyError
    payload = {
        "schema_version": application.payload.get("schema_version"),
        "data": data,
    }
    validate_payload(application.kind, payload)
    application.payload = payload
    application.save(update_fields=["payload", "modified_date"])
    return application
