from django.conf import settings
from django.contrib import admin
from django.contrib.auth import admin as auth_admin
from django.contrib.auth import decorators
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from .forms import UserAdminChangeForm
from .forms import UserAdminCreationForm

if settings.DJANGO_ADMIN_FORCE_ALLAUTH:
    # Force the `admin` sign in process to go through the `django-allauth` workflow:
    # https://docs.allauth.org/en/latest/common/admin.html#admin
    admin.autodiscover()
    admin.site.login = decorators.login_required(admin.site.login)  # type: ignore[method-assign]

User = get_user_model()


@admin.register(User)
class UserAdmin(auth_admin.UserAdmin):
    form = UserAdminChangeForm
    add_form = UserAdminCreationForm
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (_("Personal info"), {"fields": ("name", "phone_number")}),
        (
            _("Permissions"),
            {
                "description": _(
                    "Staff reach the review console. What they may decide there "
                    "is a review role, granted separately.",
                ),
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )
    list_display = [
        "email",
        "name",
        "organisation_names",
        "is_active",
        "is_staff",
    ]
    list_filter = ["is_active", "is_staff", "is_superuser"]
    search_fields = ["name", "email"]
    ordering = ["email"]
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "name", "password1", "password2", "is_staff"),
            },
        ),
    )

    def get_queryset(self, request):
        return (
            super().get_queryset(request).prefetch_related("memberships__organisation")
        )

    @admin.display(description=_("Organisations"))
    def organisation_names(self, obj) -> str:
        names = [m.organisation.name for m in obj.memberships.all()]
        return ", ".join(names) if names else "—"
