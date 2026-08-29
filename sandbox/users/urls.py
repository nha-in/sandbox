from django.urls import path

from .views import contact_verification_view
from .views import user_detail_view
from .views import user_redirect_view
from .views import user_update_view

app_name = "users"
urlpatterns = [
    path("~redirect/", view=user_redirect_view, name="redirect"),
    path("~update/", view=user_update_view, name="update"),
    path(
        "verify-contacts/",
        view=contact_verification_view,
        name="verify_contacts",
    ),
    path("<int:pk>/", view=user_detail_view, name="detail"),
]
