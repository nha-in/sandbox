from __future__ import annotations

from django.urls import path

from sandbox.console.views import ApplicationDetailView
from sandbox.console.views import DecideView
from sandbox.console.views import QueueView
from sandbox.console.views import RecordReviewView

app_name = "console"
urlpatterns = [
    path("", QueueView.as_view(), name="queue"),
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
]
