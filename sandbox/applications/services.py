"""Application services — the only writers of Application rows."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from django.db import transaction
from django.utils import timezone

from sandbox.applications.models import NON_BLOCKING_STATES
from sandbox.applications.models import Application
from sandbox.applications.models import ApplicationKind
from sandbox.applications.models import ApplicationReferenceCounter
from sandbox.applications.models import ApplicationState
from sandbox.applications.schemas import validate_envelope
from sandbox.organisations.services import create_product
from sandbox.organisations.services import rename_product
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
    validate_envelope(kind, payload)
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
def set_draft_product(*, application: Application, product: Product) -> Application:
    """Point an unsubmitted draft at a different product.

    C4's Back button needs this. Without it, stepping back from the details
    step and continuing again ran `create_draft_with_new_product` a second
    time — and because `create_product` uniquifies the slug rather than
    refusing a repeat, that silently left the organisation with a duplicate
    product and an abandoned draft, with nothing raised anywhere.
    """
    if application.state not in _EDITABLE_STATES:
        message = (
            f"cannot change the product of an application in state {application.state}"
        )
        raise DomainError(message, code="illegal_state")

    if product.organisation_id != application.product.organisation_id:
        message = "product does not belong to this organisation"
        raise DomainError(message)

    if product.pk == application.product_id:
        return application

    # The partial-unique index would refuse this anyway; saying so is kinder.
    taken = (
        Application.objects.filter(kind=application.kind, product=product)
        .exclude(state__in=NON_BLOCKING_STATES)
        .exclude(pk=application.pk)
        .exists()
    )
    if taken:
        message = "that product already has an application in flight"
        raise DomainError(message, code="product_taken")

    application.product = product
    application.save(update_fields=["product", "modified_date"])
    return application


@transaction.atomic
def set_draft_product_by_name(
    *,
    application: Application,
    product_name: str,
) -> Application:
    """`set_draft_product` for a product that does not exist yet.

    Atomic for the same reason `create_draft_with_new_product` is: a refused
    repoint must not leave the new product behind.
    """
    return set_draft_product(
        application=application,
        product=create_product(
            organisation=application.product.organisation,
            name=product_name,
        ),
    )


@transaction.atomic
def rename_draft_product(*, application: Application, name: str) -> Product:
    """Correct the name a draft's product was opened with.

    Gated on the draft still being editable: once it is with a reviewer, the
    product they are reading about must not change name underneath them.
    """
    if application.state not in _EDITABLE_STATES:
        message = (
            f"cannot rename the product of an application in state {application.state}"
        )
        raise DomainError(message, code="illegal_state")
    return rename_product(product=application.product, name=name)


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
    validate_envelope(application.kind, payload)
    application.payload = payload
    application.save(update_fields=["payload", "modified_date"])
    return application
