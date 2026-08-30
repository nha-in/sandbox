from django.urls import path

from sandbox.applications import views

app_name = "applications"
urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("enrolment/", views.EnrolmentIndexView.as_view(), name="enrolment"),
    path("new/product/", views.ProductStepView.as_view(), name="step_product"),
    # Same view, for a draft that already exists: the Back button from the
    # details step, which must correct the draft rather than open another.
    path(
        "<uuid:external_id>/product/",
        views.ProductStepView.as_view(),
        name="step_product_edit",
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
        views.CredentialsPanelView.as_view(),
        name="credentials",
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
