from __future__ import annotations

import pytest

from sandbox.catalog import selectors
from sandbox.catalog.models import Milestone

pytestmark = pytest.mark.django_db


def test_state_choices_returns_dataset_states():
    choices = selectors.state_choices()
    assert ("PENDING-01", "Placeholder State One") in choices
    assert ("PENDING-02", "Placeholder State Two") in choices


def test_districts_for_state_returns_matching_districts():
    districts = selectors.districts_for_state("PENDING-01")
    assert districts == [
        ("PENDING-01-01", "Placeholder District A"),
        ("PENDING-01-02", "Placeholder District B"),
    ]


def test_districts_for_state_unknown_state_returns_empty():
    assert selectors.districts_for_state("NOT-A-REAL-CODE") == []


def test_is_valid_state_code_rejects_unknown_code():
    assert selectors.is_valid_state_code("PENDING-01") is True
    assert selectors.is_valid_state_code("NOT-A-REAL-CODE") is False


def test_is_valid_district_code_rejects_unknown_code():
    assert selectors.is_valid_district_code("PENDING-01", "PENDING-01-01") is True
    assert selectors.is_valid_district_code("PENDING-01", "NOT-A-REAL-CODE") is False
    # a real district code under the wrong state is still rejected
    assert selectors.is_valid_district_code("PENDING-02", "PENDING-01-01") is False


def test_active_milestones_excludes_inactive():
    Milestone.objects.create(
        key="active-test",
        title="Active",
        track="TEST",
        order=0,
        is_active=True,
    )
    Milestone.objects.create(
        key="inactive-test",
        title="Inactive",
        track="TEST",
        order=1,
        is_active=False,
    )

    keys = {m.key for m in selectors.active_milestones()}

    assert "active-test" in keys
    assert "inactive-test" not in keys
