from django.urls import path

from sandbox.applications import views

app_name = "applications"
urlpatterns = [
    path("new/", views.WizardEntryView.as_view(), name="new"),
    path("new/product/", views.ProductStepView.as_view(), name="step_product"),
    path(
        "<uuid:external_id>/details/",
        views.DetailsStepView.as_view(),
        name="step_details",
    ),
    path(
        "<uuid:external_id>/review/",
        views.ReviewStepView.as_view(),
        name="step_review",
    ),
]
