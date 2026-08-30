from django.urls import path

from sandbox.declarations import views

app_name = "declarations"
urlpatterns = [
    path("milestones/", views.MilestonesView.as_view(), name="milestones"),
    path(
        "milestones/<slug:key>/declare/",
        views.DeclareMilestoneView.as_view(),
        name="declare_milestone",
    ),
    path("exit/", views.ExitView.as_view(), name="exit"),
    path(
        "documents/<uuid:external_id>/",
        views.document_download_view,
        name="document_download",
    ),
]
