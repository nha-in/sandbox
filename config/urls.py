from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include
from django.urls import path
from django.views import defaults as default_views

from sandbox.users.views import user_signup_view

urlpatterns = [
    path("", include("sandbox.pages.urls")),
    # Django Admin, use {% url 'admin:index' %}
    path(settings.ADMIN_URL, admin.site.urls),
    # User management
    path("", include("sandbox.users.urls", namespace="users")),
    path("", include("sandbox.organisations.urls", namespace="organisations")),
    path("staff/", include("sandbox.staff.urls", namespace="staff")),
    # Overrides allauth's own signup so an invitation token in the session
    # shapes the form; must precede the allauth include.
    path("accounts/signup/", user_signup_view, name="account_signup"),
    path("accounts/", include("allauth.urls")),
    path("events/", include("sandbox.events.urls", namespace="events")),
    path("support/", include("sandbox.support.urls", namespace="support")),
    path(
        "applications/",
        include("sandbox.experiences.urls", namespace="experiences"),
    ),
    # Your stuff: custom urls includes go here
    # ...
    # Media files
    *static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT),
]


if settings.DEBUG:
    # This allows the error pages to be debugged during development, just visit
    # these url in browser to see how these error pages look like.
    urlpatterns += [
        path(
            "400/",
            default_views.bad_request,
            kwargs={"exception": Exception("Bad Request!")},
        ),
        path(
            "403/",
            default_views.permission_denied,
            kwargs={"exception": Exception("Permission Denied")},
        ),
        path(
            "404/",
            default_views.page_not_found,
            kwargs={"exception": Exception("Page not Found")},
        ),
        path("500/", default_views.server_error),
    ]
    if "debug_toolbar" in settings.INSTALLED_APPS:
        import debug_toolbar

        urlpatterns = [
            path("__debug__/", include(debug_toolbar.urls)),
            *urlpatterns,
        ]
