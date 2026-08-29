"""Organisation-owned writes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import transaction
from django.utils.text import slugify

from sandbox.organisations.models import Product

if TYPE_CHECKING:
    from sandbox.organisations.models import Organisation

_SLUG_BASE_MAX_LENGTH = 200


def _unique_slug(organisation: Organisation, name: str) -> str:
    """Unique within the organisation, matching the partial-unique constraint."""
    base = slugify(name)[:_SLUG_BASE_MAX_LENGTH] or "product"
    slug = base
    suffix = 2
    while Product.objects.for_organisation(organisation).filter(slug=slug).exists():
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
