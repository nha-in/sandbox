import contextlib
from http import HTTPStatus
from importlib import reload

import pytest
from django.contrib import admin
from django.contrib.auth.models import AnonymousUser
from django.urls import reverse
from pytest_django.asserts import assertRedirects

from sandbox.organisations.models import Role
from sandbox.organisations.tests.factories import MembershipFactory
from sandbox.users.models import User
from sandbox.users.tests.factories import UserFactory


class TestUserAdmin:
    def test_changelist(self, admin_client):
        url = reverse("admin:users_user_changelist")
        response = admin_client.get(url)
        assert response.status_code == HTTPStatus.OK

    def test_search(self, admin_client):
        url = reverse("admin:users_user_changelist")
        response = admin_client.get(url, data={"q": "test"})
        assert response.status_code == HTTPStatus.OK

    def test_add(self, admin_client):
        url = reverse("admin:users_user_add")
        response = admin_client.get(url)
        assert response.status_code == HTTPStatus.OK

        response = admin_client.post(
            url,
            data={
                "email": "new-admin@example.com",
                "password1": "My_R@ndom-P@ssw0rd",
                "password2": "My_R@ndom-P@ssw0rd",
            },
        )
        assert response.status_code == HTTPStatus.FOUND
        assert User.objects.filter(email="new-admin@example.com").exists()

    def test_view_user(self, admin_client):
        user = User.objects.get(email="admin@example.com")
        url = reverse("admin:users_user_change", kwargs={"object_id": user.pk})
        response = admin_client.get(url)
        assert response.status_code == HTTPStatus.OK

    @pytest.fixture
    def _force_allauth(self, settings):
        settings.DJANGO_ADMIN_FORCE_ALLAUTH = True
        # Reload the admin module to apply the setting change
        import sandbox.users.admin as users_admin  # noqa: PLC0415

        with contextlib.suppress(admin.sites.AlreadyRegistered):  # type: ignore[attr-defined]
            reload(users_admin)

    @pytest.mark.django_db
    @pytest.mark.usefixtures("_force_allauth")
    def test_allauth_login(self, rf, settings):
        request = rf.get("/fake-url")
        request.user = AnonymousUser()
        response = admin.site.login(request)

        # The `admin` login view should redirect to the `allauth` login view
        target_url = reverse(settings.LOGIN_URL) + "?next=" + request.path
        assertRedirects(response, target_url, fetch_redirect_response=False)


@pytest.fixture
def staff_member(db) -> User:
    return UserFactory.create(
        email="anand@nha.gov.in",
        name="Anand S",
        is_staff=True,
    )


@pytest.fixture
def vendor_member(db) -> User:
    membership = MembershipFactory.create(
        organisation__name="Arogya Systems",
        user__email="meera@arogyasystems.in",
        user__name="Meera Krishnan",
        role=Role.OWNER,
    )
    return membership.user


@pytest.fixture
def staff_but_not_superuser(db) -> User:
    """Someone who can reach the admin but may not mint staff accounts."""
    return UserFactory.create(email="desk@nha.gov.in", is_staff=True)


def changelist_emails(response) -> set[str]:
    return set(response.context["cl"].queryset.values_list("email", flat=True))


class TestUserChangelist:
    def test_it_lists_both_populations(self, admin_client, staff_member, vendor_member):
        url = reverse("admin:users_user_changelist")

        response = admin_client.get(url)

        assert response.status_code == HTTPStatus.OK
        assert {staff_member.email, vendor_member.email} <= changelist_emails(response)

    def test_django_s_own_staff_filter_narrows_to_the_console(
        self,
        admin_client,
        staff_member,
        vendor_member,
    ):
        """The bespoke account-type filter went with `is_ohc_team`: staff is the
        console gate now, and Django ships a filter for it."""
        url = reverse("admin:users_user_changelist")

        response = admin_client.get(url, data={"is_staff__exact": "1"})
        emails = changelist_emails(response)

        assert staff_member.email in emails
        assert vendor_member.email not in emails

    def test_the_columns_name_the_organisations(self, staff_member, vendor_member):
        user_admin = admin.site.get_model_admin(User)

        assert user_admin.organisation_names(vendor_member) == "Arogya Systems"
        assert user_admin.organisation_names(staff_member) == "—"


class TestVendorsAreLockedOutOfTheAdmin:
    """A vendor is not staff, so the admin refuses them at the door.

    The console gate is asserted in `staff/tests/test_views.py`; this is the other
    half of the same boundary. It matters more than it did: `is_staff` now opens
    the console as well as the admin, so one flag is the whole platform side.
    """

    def test_a_vendor_cannot_open_the_changelist(self, sign_in, vendor_member):
        client = sign_in(vendor_member)

        response = client.get(reverse("admin:users_user_changelist"))

        assert response.status_code in {HTTPStatus.FOUND, HTTPStatus.FORBIDDEN}

    def test_no_action_can_hand_out_console_access(self):
        """`grant_ohc_team` was gated on `users.change_user`, so any staff
        account holding that permission could grant itself the console — a
        strict-xfail escalation this module used to carry. The action is gone
        with the flag; what remains is Django's own posture, where
        `change_user` is a powerful permission by design."""
        user_admin = admin.site.get_model_admin(User)

        assert "grant_ohc_team" not in user_admin.actions
        assert "revoke_ohc_team" not in user_admin.actions
