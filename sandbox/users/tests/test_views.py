from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import Http404
from django.http import HttpRequest
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from sandbox.organisations.tests.factories import MembershipFactory
from sandbox.users.forms import UserAdminChangeForm
from sandbox.users.tests.factories import UserFactory
from sandbox.users.tests.factories import VerifiedUserFactory
from sandbox.users.views import UserRedirectView
from sandbox.users.views import UserUpdateView
from sandbox.users.views import user_detail_view

if TYPE_CHECKING:
    from django.test import RequestFactory

    from sandbox.users.models import User

pytestmark = pytest.mark.django_db


class TestUserUpdateView:
    """
    TODO:
        extracting view initialization code as class-scoped fixture
        would be great if only pytest-django supported non-function-scoped
        fixture db access -- this is a work-in-progress for now:
        https://github.com/pytest-dev/pytest-django/pull/258
    """

    def dummy_get_response(self, request: HttpRequest):
        return None

    def test_get_success_url(self, user: User, rf: RequestFactory):
        view = UserUpdateView()
        request = rf.get("/fake-url/")
        request.user = user

        view.request = request
        assert view.get_success_url() == f"/users/{user.external_id}/"

    def test_get_object(self, user: User, rf: RequestFactory):
        view = UserUpdateView()
        request = rf.get("/fake-url/")
        request.user = user

        view.request = request

        assert view.get_object() == user

    def test_form_valid(self, user: User, rf: RequestFactory):
        view = UserUpdateView()
        request = rf.get("/fake-url/")

        # Add the session/message middleware to the request
        SessionMiddleware(self.dummy_get_response).process_request(request)
        MessageMiddleware(self.dummy_get_response).process_request(request)
        request.user = user

        view.request = request

        # Initialize the form
        form = UserAdminChangeForm()
        form.cleaned_data = {}
        form.instance = user
        view.form_valid(form)

        messages_sent = [m.message for m in messages.get_messages(request)]
        assert messages_sent == [_("Information successfully updated")]


class TestUserRedirectView:
    def test_get_redirect_url(self, user: User, rf: RequestFactory):
        view = UserRedirectView()
        request = rf.get("/fake-url")
        request.user = user

        view.request = request
        assert view.get_redirect_url() == f"/users/{user.external_id}/"


class TestUserDetailView:
    def test_own_page_renders(self, user: User, rf: RequestFactory):
        request = rf.get("/fake-url/")
        request.user = user
        response = user_detail_view(request, external_id=user.external_id)

        assert response.status_code == HTTPStatus.OK

    def test_another_users_page_is_not_found(self, user: User, rf: RequestFactory):
        """404 rather than 403: a 403 would confirm the account exists."""
        request = rf.get("/fake-url/")
        request.user = UserFactory.create()

        with pytest.raises(Http404):
            user_detail_view(request, external_id=user.external_id)

    def test_not_authenticated(self, user: User, rf: RequestFactory):
        request = rf.get("/fake-url/")
        request.user = AnonymousUser()
        response = user_detail_view(request, external_id=user.external_id)
        login_url = reverse(settings.LOGIN_URL)

        assert isinstance(response, HttpResponseRedirect)
        assert response.status_code == HTTPStatus.FOUND
        assert response.url == f"{login_url}?next=/fake-url/"


def test_verified_user_is_given_somewhere_to_go(client):
    """Both contacts verified used to leave the page saying "must be verified"
    with no onward link — a dead end you escape only via the nav."""
    user = VerifiedUserFactory.create()
    MembershipFactory.create(user=user)
    client.force_login(user)

    response = client.get(reverse("users:verify_contacts"))

    assert response.context["all_verified"] is True
    assert reverse("applications:dashboard") in response.content.decode()


def test_unverified_user_is_not_offered_the_way_out(client):
    user = UserFactory.create()
    client.force_login(user)

    response = client.get(reverse("users:verify_contacts"))

    assert response.context["all_verified"] is False
