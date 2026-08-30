from __future__ import annotations

from django.urls import path

from sandbox.organisations.views import DistrictOptionsView
from sandbox.organisations.views import OrganisationChooseView
from sandbox.organisations.views import OrganisationCreateView
from sandbox.organisations.views import OrganisationProfileView

app_name = "organisations"
urlpatterns = [
    path("new/", OrganisationCreateView.as_view(), name="create"),
    path("choose/", OrganisationChooseView.as_view(), name="choose"),
    path("profile/", OrganisationProfileView.as_view(), name="profile"),
    path("districts/", DistrictOptionsView.as_view(), name="district_options"),
]
