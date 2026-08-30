"""Organisation-owned writes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import transaction
from django.utils.text import slugify

from sandbox.organisations.models import Membership
from sandbox.organisations.models import MembershipRole
from sandbox.organisations.models import Organisation
from sandbox.organisations.models import Product

if TYPE_CHECKING:
    from sandbox.users.models import User

_SLUG_BASE_MAX_LENGTH = 200


def _unique_slug(
    organisation: Organisation,
    name: str,
    exclude_pk: int | None = None,
) -> str:
    """Unique within the organisation, matching the partial-unique constraint.

    `exclude_pk` is the product being renamed: without it, saving a product
    under its own name would walk past its own slug and append `-2`.
    """
    base = slugify(name)[:_SLUG_BASE_MAX_LENGTH] or "product"
    taken = Product.objects.for_organisation(organisation)
    if exclude_pk is not None:
        taken = taken.exclude(pk=exclude_pk)
    slug = base
    suffix = 2
    while taken.filter(slug=slug).exists():
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


@transaction.atomic
def create_product(
    *,
    organisation: Organisation,
    name: str,
    description: str = "",
) -> Product:
    return Product.objects.create(
        organisation=organisation,
        name=name,
        slug=_unique_slug(organisation, name),
        description=description,
    )


@transaction.atomic
def rename_product(*, product: Product, name: str) -> Product:
    """The slug follows the name: nothing addresses a product by it, and one
    frozen from a typo would outlive the typo."""
    product.name = name
    product.slug = _unique_slug(product.organisation, name, exclude_pk=product.pk)
    product.save(update_fields=["name", "slug", "modified_date"])
    return product


@transaction.atomic
def update_organisation_profile(
    *,
    organisation: Organisation,
    **fields: object,
) -> Organisation:
    """C4's first wizard step. Profile facts live here, never in the payload,
    so a later edit cannot leave an application showing a stale copy."""
    for name, value in fields.items():
        setattr(organisation, name, value)
    organisation.save(update_fields=[*fields, "modified_date"])
    return organisation


def _unique_organisation_slug(name: str) -> str:
    base = slugify(name)[:_SLUG_BASE_MAX_LENGTH] or "organisation"
    slug = base
    suffix = 2
    while Organisation.objects.filter(slug=slug).exists():
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


@transaction.atomic
def create_organisation(
    *,
    creator: User,
    name: str,
    kind: str,
    **profile: object,
) -> Organisation:
    """The front door. Sign-up creates a user with no tenant, so without this
    a self-registered integrator can never reach enrolment at all.

    The creator becomes OWNER; the organisation stays PENDING until staff
    verify it, so creating one grants no standing of its own.
    """
    organisation = Organisation.objects.create(
        name=name,
        slug=_unique_organisation_slug(name),
        kind=kind,
        **profile,
    )
    Membership.objects.create(
        organisation=organisation,
        user=creator,
        role=MembershipRole.OWNER,
    )
    return organisation
