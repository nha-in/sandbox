"""Validator tests (C4).

Each case is one thing the legacy rules got wrong, or one thing they got right
and must keep doing.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from sandbox.organisations.validators import validate_gstin
from sandbox.organisations.validators import validate_name
from sandbox.organisations.validators import validate_pincode
from sandbox.organisations.validators import validate_plain_text


@pytest.mark.parametrize(
    "value",
    [
        "12/A, MG Road",
        "St. Mary's Hospital (Annexe)",
        "Tiruvananthapuram",
        "R&D Wing #4",
    ],
)
def test_plain_text_accepts_real_addresses(value):
    validate_plain_text(value)


@pytest.mark.parametrize(
    "value",
    [
        "<script>alert(1)</script>",
        "ok<script>",  # legacy's unanchored pattern let this through
        "name\x00null",
        "a\nb",
    ],
)
def test_plain_text_rejects_markup_and_control_characters(value):
    with pytest.raises(ValidationError):
        validate_plain_text(value)


def test_name_requires_something_nameable():
    validate_name("Care Bridge")
    with pytest.raises(ValidationError):
        validate_name("--- ")


@pytest.mark.parametrize("value", ["29ABCDE1234F1Z5", "29abcde1234f1z5"])
def test_gstin_accepts_valid_numbers_in_either_case(value):
    validate_gstin(value)


@pytest.mark.parametrize(
    "value",
    ["29ABCDE1234F1Z", "ABCDE1234F1Z5XX", "29ABCDE1234F1Y5", ""],
)
def test_gstin_rejects_malformed_numbers(value):
    with pytest.raises(ValidationError):
        validate_gstin(value)


def test_pincode_rejects_a_leading_zero():
    validate_pincode("682001")
    for value in ("082001", "68200", "6820011", "abcdef"):
        with pytest.raises(ValidationError):
            validate_pincode(value)
