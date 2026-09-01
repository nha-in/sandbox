"""Role management: who may edit authority, and what they may hand out.

The load-bearing test is `test_a_role_cannot_grant_role_management`. Everything
else here is CRUD; that one is the reason an admin who can edit roles cannot
quietly promote themselves.
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission
from django.urls import reverse

from sandbox.audit.models import AuditEvent
from sandbox.console.tests.conftest import grant
from sandbox.console.tests.conftest import signed_in
from sandbox.users.models import User
from sandbox.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

HTTP_OK = 200
HTTP_FOUND = 302
HTTP_FORBIDDEN = 403


@pytest.fixture
def role_admin(enable_mfa):
    user = grant(UserFactory.create(is_staff=True), "manage_roles")
    return signed_in(enable_mfa(user))


def _permission(codename: str) -> Permission:
    return Permission.objects.get(codename=codename)


def test_staff_without_the_permission_cannot_reach_roles(reviewer_client):
    """A reviewer holds authority over applications, not over authority."""
    assert reviewer_client.get(reverse("console:roles")).status_code == HTTP_FORBIDDEN


def test_creating_a_role_records_what_it_grants(role_admin):
    response = role_admin.post(
        reverse("console:roles"),
        {
            "name": "ABDM review team",
            "permissions": [_permission("view_abdm").pk, _permission("review_abdm").pk],
        },
    )

    assert response.status_code == HTTP_FOUND
    role = Group.objects.get(name="ABDM review team")
    assert set(role.permissions.values_list("codename", flat=True)) == {
        "view_abdm",
        "review_abdm",
    }


def test_giving_someone_a_role_gives_them_its_permissions(role_admin):
    person = UserFactory.create(is_staff=True)
    role = Group.objects.create(name="ABDM review team")
    role.permissions.add(_permission("view_abdm"), _permission("review_abdm"))

    role_admin.post(
        reverse("console:user_roles", kwargs={"external_id": person.external_id}),
        {"roles": [role.pk]},
    )

    # re-read: the permission cache is per instance and already warm
    assert User.objects.get(pk=person.pk).has_perm("workflow.review_abdm")


def test_taking_a_role_away_takes_the_authority_with_it(role_admin):
    person = UserFactory.create(is_staff=True)
    role = Group.objects.create(name="ABDM review team")
    role.permissions.add(_permission("view_abdm"))
    person.groups.add(role)

    role_admin.post(
        reverse("console:user_roles", kwargs={"external_id": person.external_id}),
        {"roles": []},
    )

    assert not User.objects.get(pk=person.pk).has_perm("workflow.view_abdm")


def test_a_role_change_is_audited_against_the_person(role_admin):
    person = UserFactory.create(is_staff=True, email="new.reviewer@example.gov.in")
    role = Group.objects.create(name="ABDM review team")

    role_admin.post(
        reverse("console:user_roles", kwargs={"external_id": person.external_id}),
        {"roles": [role.pk]},
    )

    event = AuditEvent.objects.get(action="user.roles_changed")
    assert event.data["subject"] == "new.reviewer@example.gov.in"
    assert event.data["before"] == []
    assert event.data["after"] == ["ABDM review team"]


def test_the_users_page_lists_console_staff_and_their_roles(role_admin):
    person = UserFactory.create(is_staff=True, email="on.a.team@example.gov.in")
    integrator = UserFactory.create(email="integrator@example.gov.in")
    role = Group.objects.create(name="ABDM review team")
    person.groups.add(role)

    body = role_admin.get(reverse("console:users")).content.decode()

    assert "on.a.team@example.gov.in" in body
    assert "ABDM review team" in body
    # an integrator never holds a role, so they are not on this screen
    assert integrator.email not in body


def test_only_a_role_admin_reaches_the_users_page(reviewer_client):
    assert reviewer_client.get(reverse("console:users")).status_code == HTTP_FORBIDDEN


def test_a_role_cannot_grant_role_management(role_admin):
    """Otherwise anyone who may edit a role may grant themselves every one —
    the standard RBAC escalation. `manage_roles` comes from a superuser."""
    response = role_admin.post(
        reverse("console:roles"),
        {
            "name": "Sneaky",
            "permissions": [_permission("manage_roles").pk],
        },
    )

    assert response.status_code == HTTP_OK
    assert response.context["form"].errors["permissions"]
    assert not Group.objects.filter(name="Sneaky").exists()


def test_editing_a_role_changes_what_its_members_may_do(role_admin):
    member = UserFactory.create(is_staff=True)
    role = Group.objects.create(name="ABDM review team")
    role.permissions.add(_permission("view_abdm"), _permission("review_abdm"))
    member.groups.add(role)

    role_admin.post(
        reverse("console:role_detail", kwargs={"pk": role.pk}),
        {
            "name": "ABDM review team",
            "permissions": [_permission("view_abdm").pk],
        },
    )

    # re-read: the permission cache is per instance and already warm
    assert not User.objects.get(pk=member.pk).has_perm("workflow.review_abdm")


def test_deleting_a_role_is_audited(role_admin):
    role = Group.objects.create(name="Temporary")
    role.permissions.add(_permission("approve_abdm"))

    role_admin.post(
        reverse("console:role_detail", kwargs={"pk": role.pk}),
        {"action": "delete"},
    )

    assert not Group.objects.filter(name="Temporary").exists()
    event = AuditEvent.objects.get(action="role.deleted")
    assert event.data["role"] == "Temporary"
    assert event.data["permissions"] == ["approve_abdm"]


def test_every_role_change_is_audited(role_admin):
    role_admin.post(
        reverse("console:roles"),
        {"name": "ABDM review team", "permissions": [_permission("view_abdm").pk]},
    )

    event = AuditEvent.objects.get(action="role.created")
    assert event.data["role"] == "ABDM review team"
    assert event.data["permissions"] == ["view_abdm"]


def test_the_editor_opens_with_what_the_role_already_grants(role_admin):
    """`permissions` sits outside Meta.fields, so ModelForm does not seed it.
    Unticked boxes on open meant saving any other edit stripped the role."""
    role = Group.objects.create(name="ABDM review team")
    role.permissions.add(_permission("view_abdm"), _permission("review_abdm"))

    response = role_admin.get(
        reverse("console:role_detail", kwargs={"pk": role.pk}),
    )

    ticked = {
        permission["label"]
        for group in response.context["form"].permission_groups()
        for permission in group["permissions"]
        if permission["checked"]
    }
    assert ticked == {
        "Can see ABDM applications in the console",
        "Can record a review on an ABDM application",
    }


def test_the_user_page_opens_with_the_roles_already_held(role_admin):
    person = UserFactory.create(is_staff=True)
    role = Group.objects.create(name="ABDM review team")
    person.groups.add(role)

    response = role_admin.get(
        reverse("console:user_roles", kwargs={"external_id": person.external_id}),
    )

    # prepare_value() hands the widget pks, which is what ticks the boxes
    assert list(response.context["form"]["roles"].value()) == [role.pk]


def test_permissions_are_grouped_by_programme_and_named_plainly(role_admin):
    """A flat list of every programme's permissions is what this replaced, and
    Django's own label ("Workflow | workflow transition | ...") is not a label
    an administrator should have to read past."""
    response = role_admin.get(reverse("console:roles"))

    groups = response.context["form"].permission_groups()
    assert [group["programme"] for group in groups] == ["ABDM"]
    body = response.content.decode()
    assert "Can approve an ABDM application" in body
    assert "workflow transition |" not in body


def test_only_programme_permissions_are_offered(role_admin):
    """Django's own add/change/delete rows would be noise, and `manage_roles`
    is deliberately absent."""
    body = role_admin.get(reverse("console:roles")).content.decode()

    assert "Can approve an ABDM application" in body
    assert "Can create and edit console roles" not in body
    assert "Can add workflow transition" not in body
