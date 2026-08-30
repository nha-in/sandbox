from django.urls import path

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
]
