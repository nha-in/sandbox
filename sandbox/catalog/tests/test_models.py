from __future__ import annotations

import pytest

from sandbox.catalog.models import Milestone

pytestmark = pytest.mark.django_db


def test_str_returns_title():
    milestone = Milestone(title="ABHA Creation/Verification - M1")
    assert str(milestone) == "ABHA Creation/Verification - M1"


def test_ordering_is_track_then_order():
    Milestone.objects.create(
        key="order-test-second",
        title="Second",
        track="ORDER_TEST",
        order=2,
    )
    Milestone.objects.create(
        key="order-test-first",
        title="First",
        track="ORDER_TEST",
        order=1,
    )

    keys = list(
        Milestone.objects.filter(track="ORDER_TEST").values_list("key", flat=True),
    )

    assert keys == ["order-test-first", "order-test-second"]


def test_key_unique_only_among_non_deleted():
    original = Milestone.objects.create(
        key="dupe-key-test",
        title="Original",
        track="TEST",
        order=0,
    )
    original.delete()  # soft delete flips `deleted`, key becomes free again

    recreated = Milestone.objects.create(
        key="dupe-key-test",
        title="Recreated",
        track="TEST",
        order=0,
    )
    pks_with_key = set(
        Milestone.all_objects.filter(key="dupe-key-test").values_list("pk", flat=True),
    )

    assert recreated.pk != original.pk
    assert Milestone.objects.filter(key="dupe-key-test").count() == 1
    assert pks_with_key == {original.pk, recreated.pk}


def test_default_manager_hides_soft_deleted():
    milestone = Milestone.objects.create(
        key="soft-delete-test",
        title="Soft Delete Test",
        track="TEST",
        order=0,
    )
    milestone.delete()

    assert not Milestone.objects.filter(pk=milestone.pk).exists()
    assert Milestone.all_objects.filter(pk=milestone.pk).exists()
