from __future__ import annotations

from django.urls import path

from sandbox.organisations.views import OrganisationSwitchView

app_name = "organisations"
urlpatterns = [
    path("switch/", OrganisationSwitchView.as_view(), name="switch"),
]
