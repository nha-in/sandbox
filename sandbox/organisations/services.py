"""Writes for the organisations app."""

from __future__ import annotations

from django.utils.text import slugify

from .models import Product


def normalise_product_name(name: str) -> str:
    """The key two spellings of one product must agree on.

    Matching on the raw string counts "Arogya HMIS" and "arogya-hmis" as two
    products; the legacy dump is full of exactly that, which is why the
    importer normalises too (`13-legacy-import.md` §7.2).
    """
    return slugify(name)


def match_or_create_product(*, organisation, name: str) -> Product | None:
    """The organisation's product of that name, created if it has none.

    None when the name is blank: most legacy registrations name no product at
    all, and a placeholder would be indistinguishable from a real one (§1.2).
    """
    cleaned = (name or "").strip()
    slug = normalise_product_name(cleaned)
    if not slug:
        return None
    product, _created = Product.objects.get_or_create(
        organisation=organisation,
        slug=slug,
        defaults={"name": cleaned},
    )
    return product
