from django.urls import path

from sandbox.declarations import views

app_name = "declarations"

# Mounted at the root rather than under a prefix of its own, because these
# screens belong to an application and live under its URL. One namespace cannot
# be mounted at two prefixes without `reverse()` having to guess between them,
# so the paths are spelled in full here instead.
_APPLICATION = "applications/<uuid:external_id>/"

urlpatterns = [
    path(
        f"{_APPLICATION}milestones/",
        views.MilestonesView.as_view(),
        name="milestones",
    ),
    path(
        f"{_APPLICATION}milestones/<slug:key>/declare/",
        views.DeclareMilestoneView.as_view(),
        name="declare_milestone",
    ),
    path(f"{_APPLICATION}exit/", views.ExitView.as_view(), name="exit"),
    # A stored document is reached by its own id and scoped by organisation, so
    # it hangs off no single application.
    path(
        "declarations/documents/<uuid:external_id>/",
        views.document_download_view,
        name="document_download",
    ),
]
