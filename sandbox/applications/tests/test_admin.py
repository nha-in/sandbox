from __future__ import annotations

from http import HTTPStatus

from django.contrib import admin as django_admin
from django.urls import reverse

from sandbox.applications.admin import ApplicationAdmin
from sandbox.applications.models import Application
from sandbox.applications.tests.factories import ApplicationFactory


def test_application_changelist(admin_client, db):
    ApplicationFactory.create()
    response = admin_client.get(reverse("admin:applications_application_changelist"))
    assert response.status_code == HTTPStatus.OK


def test_application_change_view(admin_client, db):
    application = ApplicationFactory.create()
    url = reverse(
        "admin:applications_application_change",
        kwargs={"object_id": application.pk},
    )
    response = admin_client.get(url)
    assert response.status_code == HTTPStatus.OK


def test_application_admin_disallows_add():
    admin = ApplicationAdmin(Application, django_admin.site)
    assert admin.has_add_permission(request=None) is False


def test_application_admin_disallows_delete():
    admin = ApplicationAdmin(Application, django_admin.site)
    assert admin.has_delete_permission(request=None) is False
