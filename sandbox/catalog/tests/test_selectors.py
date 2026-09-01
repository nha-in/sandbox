from __future__ import annotations

import pytest

from sandbox.catalog import selectors
from sandbox.organisations.models import Organisation

pytestmark = pytest.mark.django_db


def test_state_choices_returns_dataset_states():
    choices = selectors.state_choices()
    assert ("PENDING-01", "Placeholder State One") in choices
    assert ("PENDING-02", "Placeholder State Two") in choices


def test_districts_for_state_returns_matching_districts():
    districts = selectors.districts_for_state("PENDING-01")
    assert districts == [
        ("PEND-01-01", "Placeholder District A"),
        ("PEND-01-02", "Placeholder District B"),
    ]


def test_districts_for_state_unknown_state_returns_empty():
    assert selectors.districts_for_state("NOT-A-REAL-CODE") == []


def test_is_valid_state_code_rejects_unknown_code():
    assert selectors.is_valid_state_code("PENDING-01") is True
    assert selectors.is_valid_state_code("NOT-A-REAL-CODE") is False


def test_is_valid_district_code_rejects_unknown_code():
    assert selectors.is_valid_district_code("PENDING-01", "PEND-01-01") is True
    assert selectors.is_valid_district_code("PENDING-01", "NOT-A-REAL-CODE") is False
    # a real district code under the wrong state is still rejected
    assert selectors.is_valid_district_code("PENDING-02", "PEND-01-01") is False


def test_every_code_fits_the_column_that_stores_it():
    """The dataset is only useful if an organisation can hold what it offers.

    The placeholder shipped 13-character district codes against a 10-character
    column, which nothing caught until the wizard first tried to save one.
    """
    fields = Organisation._meta  # noqa: SLF001 (the documented way to read a column's width)
    state_width = fields.get_field("lgd_state_code").max_length or 0
    district_width = fields.get_field("lgd_district_code").max_length or 0

    for code, _name in selectors.state_choices():
        assert len(code) <= state_width, f"state code {code!r} exceeds the column"
        for district_code, _district_name in selectors.districts_for_state(code):
            assert len(district_code) <= district_width, (
                f"district code {district_code!r} exceeds the column"
            )
