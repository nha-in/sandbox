"""Reads over organisations and membership."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sandbox.organisations.models import Membership
from sandbox.organisations.models import MembershipRole

if TYPE_CHECKING:
    from sandbox.organisations.models import Organisation
    from sandbox.users.models import User


def is_owner(organisation: Organisation, user: User) -> bool:
    """Whether `user` holds the OWNER role in `organisation`.

    Today every organisation has exactly one member and they are its OWNER —
    invites are P2 — so this separates nothing yet. It is here so that the
    destructive actions are already written against the role rather than
    against "is a member", which is the thing that will stop being true.
    """
    if not user.is_authenticated:
        return False
    return Membership.objects.filter(
        organisation=organisation,
        user=user,
        role=MembershipRole.OWNER,
    ).exists()
