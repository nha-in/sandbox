from __future__ import annotations

from django.urls import path

from sandbox.theme.views import StyleguideView

app_name = "theme"
urlpatterns = [
    path("", StyleguideView.as_view(), name="styleguide"),
]
