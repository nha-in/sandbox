from django.urls import path

from sandbox.declarations.views import document_download_view

app_name = "declarations"
urlpatterns = [
    path(
        "documents/<uuid:external_id>/",
        document_download_view,
        name="document_download",
    ),
]
