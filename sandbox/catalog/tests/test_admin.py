from __future__ import annotations

from http import HTTPStatus

from django.urls import reverse

from sandbox.catalog.models import Milestone


def test_changelist(admin_client):
    url = reverse("admin:catalog_milestone_changelist")
    response = admin_client.get(url)
    assert response.status_code == HTTPStatus.OK


def test_search(admin_client):
    url = reverse("admin:catalog_milestone_changelist")
    response = admin_client.get(url, data={"q": "M1"})
    assert response.status_code == HTTPStatus.OK


def test_view_milestone(admin_client, db):
    milestone = Milestone.objects.create(
        key="admin-view-test",
        title="Admin View Test",
        track="TEST",
        order=0,
    )
    url = reverse("admin:catalog_milestone_change", kwargs={"object_id": milestone.pk})
    response = admin_client.get(url)
    assert response.status_code == HTTPStatus.OK
