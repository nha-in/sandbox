"""Role writes. A role is a Django `Group`: a name and a set of permissions.

Every change here alters who may decide what, so each one is audited. The
console is the only caller; the escalation guard lives in `forms.py`, which
decides what a role may be granted at all.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import transaction

from sandbox.audit.services import emit

if TYPE_CHECKING:
    from django.contrib.auth.models import Group

    from sandbox.users.models import User


def _describe(role: Group) -> dict:
    return {
        "role": role.name,
        "permissions": sorted(
            role.permissions.values_list("codename", flat=True),
        ),
        "members": sorted(role.user_set.values_list("email", flat=True)),
    }


@transaction.atomic
def save_role(*, form, actor: User, creating: bool) -> Group:
    """Persist a role and what it grants, and say so in the audit log."""
    role = form.save()
    role.permissions.set(form.cleaned_data["permissions"])

    emit(
        "role.created" if creating else "role.updated",
        actor=actor,
        data=_describe(role),
    )
    return role


@transaction.atomic
def delete_role(*, role: Group, actor: User) -> None:
    """Remove a role. Everyone in it loses whatever it granted."""
    described = _describe(role)
    role.delete()
    emit("role.deleted", actor=actor, data=described)


@transaction.atomic
def set_user_roles(*, user: User, roles, actor: User) -> None:
    """Replace this person's roles. Authority changes the moment it commits."""
    before = sorted(user.groups.values_list("name", flat=True))
    user.groups.set(roles)
    after = sorted(user.groups.values_list("name", flat=True))
    if before == after:
        return

    emit(
        "user.roles_changed",
        obj=user,
        actor=actor,
        data={"subject": user.email, "before": before, "after": after},
    )
