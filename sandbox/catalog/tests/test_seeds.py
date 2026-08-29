from __future__ import annotations

import pytest
from django.core.management import call_command

from sandbox.catalog.models import Milestone

pytestmark = pytest.mark.django_db


def test_seed_catalog_creates_the_sandbox_milestones():
    call_command("seed_catalog")

    keys = set(Milestone.objects.values_list("key", flat=True))
    assert keys == {"m1", "m2", "m3", "m4", "phr", "health_locker"}


def test_seed_catalog_is_idempotent():
    call_command("seed_catalog")
    before = Milestone.objects.count()

    call_command("seed_catalog")

    assert Milestone.objects.count() == before


def test_seed_catalog_updates_existing_rows_by_key():
    call_command("seed_catalog")
    m1 = Milestone.objects.get(key="m1")
    m1.title = "stale title"
    m1.save(update_fields=["title"])

    call_command("seed_catalog")

    m1.refresh_from_db()
    assert m1.title == "ABHA Creation/Verification - M1"
