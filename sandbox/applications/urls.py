from django.urls import path

from sandbox.applications import journey_views
from sandbox.applications import views

app_name = "applications"
urlpatterns = [
    path("", views.ApplicationIndexView.as_view(), name="index"),
    path("new/product/", views.ProductStepView.as_view(), name="step_product"),
    # Same view, for a draft that already exists: the Back button from the
    # details step, which must correct the draft rather than open another.
    path(
        "<uuid:external_id>/product/",
        views.ProductStepView.as_view(),
        name="step_product_edit",
    ),
    path(
        "<uuid:external_id>/",
        views.ApplicationOverviewView.as_view(),
        name="overview",
    ),
    path(
        "<uuid:external_id>/details/",
        views.DetailsStepView.as_view(),
        name="step_details",
    ),
    path(
        "<uuid:external_id>/status/",
        views.ApplicationStatusView.as_view(),
        name="application_status",
    ),
    path(
        "<uuid:external_id>/credentials/",
        views.CredentialsView.as_view(),
        name="credentials",
    ),
    # The same panel as a fragment, for htmx to poll while the chain runs.
    path(
        "<uuid:external_id>/credentials/panel/",
        views.CredentialsPanelView.as_view(),
        name="credentials_panel",
    ),
    path(
        "<uuid:external_id>/credentials/reveal/",
        views.RevealCredentialsView.as_view(),
        name="reveal_credentials",
    ),
    path(
        "<uuid:external_id>/credentials/rotate/",
        views.RotateCredentialsView.as_view(),
        name="rotate_credentials",
    ),
    path(
        "<uuid:external_id>/review/",
        views.ReviewStepView.as_view(),
        name="step_review",
    ),
    # The journey after provisioning: what you built, and taking it live.
    path(
        "<uuid:external_id>/milestones/",
        journey_views.MilestonesView.as_view(),
        name="milestones",
    ),
    path(
        "<uuid:external_id>/milestones/<slug:key>/declare/",
        journey_views.DeclareMilestoneView.as_view(),
        name="declare_milestone",
    ),
    path("<uuid:external_id>/exit/", journey_views.ExitView.as_view(), name="exit"),
    # A finished attempt, addressed by its place in the order it was sent:
    # transitions are append-only and carry no external_id of their own.
    path(
        "<uuid:external_id>/exit/<uuid:exit_id>/attempt/<int:ordinal>/",
        journey_views.ExitAttemptView.as_view(),
        name="exit_attempt",
    ),
    # The exit wizard. Three screens because saving a step and asking NHA to
    # review the lot are different acts and must be different clicks.
    path(
        "<uuid:external_id>/exit/claim/",
        journey_views.ExitClaimStepView.as_view(),
        name="exit_claim",
    ),
    path(
        "<uuid:external_id>/exit/wasa/",
        journey_views.ExitWasaStepView.as_view(),
        name="exit_wasa",
    ),
    path(
        "<uuid:external_id>/exit/review/",
        journey_views.ExitReviewStepView.as_view(),
        name="exit_review",
    ),
    path("<uuid:external_id>/dhis/", journey_views.DhisView.as_view(), name="dhis"),
    # A stored document is reached by its own id and scoped by organisation, so
    # it hangs off no single application.
    path(
        "documents/<uuid:external_id>/",
        journey_views.document_download_view,
        name="document_download",
    ),
]
