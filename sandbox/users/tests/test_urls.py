from __future__ import annotations

from typing import TYPE_CHECKING

from django.urls import resolve
from django.urls import reverse

if TYPE_CHECKING:
    from sandbox.users.models import User


def test_detail(user: User):
    assert (
        reverse("users:detail", kwargs={"external_id": user.external_id})
        == f"/users/{user.external_id}/"
    )
    assert resolve(f"/users/{user.external_id}/").view_name == "users:detail"


def test_update():
    assert reverse("users:update") == "/users/~update/"
    assert resolve("/users/~update/").view_name == "users:update"


def test_redirect():
    assert reverse("users:redirect") == "/users/~redirect/"
    assert resolve("/users/~redirect/").view_name == "users:redirect"
