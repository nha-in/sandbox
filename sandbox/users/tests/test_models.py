from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.core.exceptions import ValidationError

if TYPE_CHECKING:
    from sandbox.users.models import User


def test_user_get_absolute_url(user: User):
    assert user.get_absolute_url() == f"/users/{user.pk}/"


def test_user_has_a_unique_external_id(user: User):
    assert user.external_id is not None


@pytest.mark.parametrize("phone", ["+919876543210", "9876543210", ""])
def test_valid_phone_numbers_pass_validation(user: User, phone: str):
    user.phone = phone
    user.full_clean(exclude=["password"])


@pytest.mark.parametrize("phone", ["abc", "123", "not-a-phone-number"])
def test_invalid_phone_numbers_fail_validation(user: User, phone: str):
    user.phone = phone
    with pytest.raises(ValidationError):
        user.full_clean(exclude=["password"])
