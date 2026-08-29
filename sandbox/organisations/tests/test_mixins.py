from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import Http404
from django.http import HttpResponse
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.views import View

from sandbox.organisations.mixins import ACTIVE_ORGANISATION_SESSION_KEY
from sandbox.organisations.mixins import OrganisationMixin
from sandbox.organisations.models import Product
from sandbox.organisations.tests.factories import MembershipFactory
from sandbox.organisations.tests.factories import OrganisationFactory
from sandbox.organisations.tests.factories import ProductFactory
from sandbox.users.tests.factories import UserFactory

if TYPE_CHECKING:
    from django.test import RequestFactory

pytestmark = pytest.mark.django_db


class _ProbeView(OrganisationMixin, View):
    """Minimal consumer used only to exercise the mixin in tests."""

    def get(self, request, *args, **kwargs):
        return HttpResponse(str(self.organisation.external_id))


class _ProductProbeView(OrganisationMixin, View):
    """Proves the wrong-org → 404 property when combined with `for_organisation`."""

    def get(self, request, *args, **kwargs):
        product = get_object_or_404(
            Product.objects.for_organisation(self.organisation),
            external_id=kwargs["external_id"],
        )
        return HttpResponse(str(product.external_id))


def _build_request(rf: RequestFactory, user, path="/probe/"):
    request = rf.get(path)
    SessionMiddleware(lambda r: HttpResponse()).process_request(request)
    request.session.save()
    request.user = user
    return request


def test_anonymous_user_gets_404(rf: RequestFactory):
    request = _build_request(rf, AnonymousUser())
    with pytest.raises(Http404):
        _ProbeView.as_view()(request)


def test_user_with_no_memberships_gets_404(rf: RequestFactory):
    user = UserFactory.create()
    request = _build_request(rf, user)
    with pytest.raises(Http404):
        _ProbeView.as_view()(request)


def test_single_membership_auto_selects_organisation(rf: RequestFactory):
    membership = MembershipFactory.create()
    request = _build_request(rf, membership.user)

    response = _ProbeView.as_view()(request)

    assert isinstance(response, HttpResponse)  # type guard
    assert response.status_code == 200  # noqa: PLR2004
    assert response.content.decode() == str(membership.organisation.external_id)
    assert (
        request.session[ACTIVE_ORGANISATION_SESSION_KEY] == membership.organisation_id
    )


def test_multiple_memberships_without_selection_redirects_to_switcher(
    rf: RequestFactory,
):
    user = UserFactory.create()
    MembershipFactory.create(user=user)
    MembershipFactory.create(user=user)
    request = _build_request(rf, user)

    response = _ProbeView.as_view()(request)

    assert isinstance(response, HttpResponseRedirect)  # type guard
    assert response.status_code == 302  # noqa: PLR2004
    assert response.url.startswith("/organisations/switch/")


def test_multiple_memberships_with_session_selection_resolves_it(rf: RequestFactory):
    user = UserFactory.create()
    MembershipFactory.create(user=user)
    selected = MembershipFactory.create(user=user)
    request = _build_request(rf, user)
    request.session[ACTIVE_ORGANISATION_SESSION_KEY] = selected.organisation_id

    response = _ProbeView.as_view()(request)

    assert isinstance(response, HttpResponse)  # type guard
    assert response.status_code == 200  # noqa: PLR2004
    assert response.content.decode() == str(selected.organisation.external_id)


def test_wrong_organisation_record_is_404_not_403(rf: RequestFactory):
    org_a = OrganisationFactory.create()
    org_b = OrganisationFactory.create()
    product = ProductFactory.create(organisation=org_a)
    member_of_b = MembershipFactory.create(organisation=org_b).user

    request = _build_request(rf, member_of_b)

    with pytest.raises(Http404):
        _ProductProbeView.as_view()(request, external_id=product.external_id)


def test_own_organisation_record_is_found(rf: RequestFactory):
    membership = MembershipFactory.create()
    product = ProductFactory.create(organisation=membership.organisation)
    request = _build_request(rf, membership.user)

    response = _ProductProbeView.as_view()(request, external_id=product.external_id)

    assert response.status_code == 200  # noqa: PLR2004
