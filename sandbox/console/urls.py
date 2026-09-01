from __future__ import annotations

from django.urls import path

from sandbox.console.views import ApplicationDetailView
from sandbox.console.views import DecideView
from sandbox.console.views import DocumentDownloadView
from sandbox.console.views import QueueView
from sandbox.console.views import RecordReviewView
from sandbox.console.views import RetryProvisioningView
from sandbox.console.views import RoleDetailView
from sandbox.console.views import RoleListView
from sandbox.console.views import UserListView
from sandbox.console.views import UserRolesView

app_name = "console"
urlpatterns = [
    path("", QueueView.as_view(), name="queue"),
    path("roles/", RoleListView.as_view(), name="roles"),
    path("roles/<int:pk>/", RoleDetailView.as_view(), name="role_detail"),
    path("users/", UserListView.as_view(), name="users"),
    path(
        "users/<uuid:external_id>/",
        UserRolesView.as_view(),
        name="user_roles",
    ),
    path(
        "applications/<uuid:external_id>/",
        ApplicationDetailView.as_view(),
        name="application_detail",
    ),
    path(
        "applications/<uuid:external_id>/review/",
        RecordReviewView.as_view(),
        name="record_review",
    ),
    path(
        "applications/<uuid:external_id>/decide/",
        DecideView.as_view(),
        name="decide",
    ),
    path(
        "applications/<uuid:external_id>/retry-provisioning/",
        RetryProvisioningView.as_view(),
        name="retry_provisioning",
    ),
    path(
        "documents/<uuid:external_id>/",
        DocumentDownloadView.as_view(),
        name="document_download",
    ),
]
