from django import forms
from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import ApplicationAccess
from .models import ApplicationAttachment
from .models import ApplicationEvent
from .models import ApplicationFormSubmission
from .models import ApplicationInstance
from .models import ApplicationQueryMessage
from .models import ApplicationQueryThread
from .models import ReviewRole
from .models import ReviewRoleAssignment
from .models import declared_permission_keys


class SubmissionInline(admin.TabularInline):
    model = ApplicationFormSubmission
    extra = 0
    readonly_fields = ["form_key", "revision", "submitted_by", "updated_at"]


class AccessInline(admin.TabularInline):
    model = ApplicationAccess
    extra = 0
    autocomplete_fields = ["user", "granted_by"]


@admin.register(ApplicationInstance)
class ApplicationInstanceAdmin(admin.ModelAdmin):
    list_display = [
        "reference",
        "application_type",
        "organisation",
        "status",
        "created_by",
        "updated_at",
    ]
    list_filter = ["application_type", "status"]
    search_fields = ["reference", "title", "organisation__name"]
    autocomplete_fields = ["organisation", "created_by", "decided_by"]
    readonly_fields = ["reference", "created_at", "updated_at"]
    inlines = [SubmissionInline, AccessInline]


@admin.register(ApplicationEvent)
class ApplicationEventAdmin(admin.ModelAdmin):
    list_display = ["application", "kind", "title", "actor", "created_at"]
    list_filter = ["kind", "application__application_type"]
    search_fields = ["application__reference", "title", "description"]
    readonly_fields = [
        "application",
        "submission",
        "actor",
        "kind",
        "title",
        "description",
        "action_key",
        "status_before",
        "status_after",
        "payload",
        "created_at",
    ]

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False


admin.site.register(ApplicationAttachment)
admin.site.register(ApplicationQueryThread)
admin.site.register(ApplicationQueryMessage)


class ReviewRoleForm(forms.ModelForm):
    """Permissions are picked from the registry, never typed.

    This is the whole safety property of plan 12 §5.2: legacy let an
    administrator name a permission nothing checked, and four of its seven
    decision permissions turned out to match nothing at all. Here the choices
    *are* the declared keys, so an unmatchable role cannot be created.
    """

    permissions = forms.MultipleChoiceField(
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text=_("Only permissions the application registry declares."),
    )

    class Meta:
        model = ReviewRole
        fields = ["key", "name", "description", "permissions", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["permissions"].choices = [
            (key, key) for key in sorted(declared_permission_keys())
        ]


@admin.register(ReviewRole)
class ReviewRoleAdmin(admin.ModelAdmin):
    form = ReviewRoleForm
    list_display = ["name", "key", "permission_count", "assignment_count", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["key", "name"]

    @admin.display(description=_("Permissions"))
    def permission_count(self, obj) -> int:
        return len(obj.permissions or [])

    @admin.display(description=_("People"))
    def assignment_count(self, obj) -> int:
        return obj.assignments.count()


@admin.register(ReviewRoleAssignment)
class ReviewRoleAssignmentAdmin(admin.ModelAdmin):
    list_display = ["user", "role", "granted_by", "created_at"]
    list_filter = ["role"]
    search_fields = ["user__email", "user__name"]
    autocomplete_fields = ["user", "role"]

    def save_model(self, request, obj, form, change) -> None:
        # Who granted this is the question an access review actually asks.
        if not change and obj.granted_by_id is None:
            obj.granted_by = request.user
        super().save_model(request, obj, form, change)
