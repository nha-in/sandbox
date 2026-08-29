"""Read-only: `services.py` is the only writer of Application rows."""

from __future__ import annotations

from django.contrib import admin

from sandbox.applications.models import Application


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = [
        "reference",
        "kind",
        "state",
        "product",
        "applicant",
        "created_date",
    ]
    list_filter = ["kind", "state"]
    search_fields = ["reference", "product__name", "applicant__email"]
    readonly_fields = [
        "external_id",
        "reference",
        "kind",
        "product",
        "applicant",
        "state",
        "payload",
        "submitted_at",
        "created_date",
        "modified_date",
    ]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
