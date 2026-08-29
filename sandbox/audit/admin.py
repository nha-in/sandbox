"""Read-only admin: audit rows are evidence, so nothing here may edit them."""

from __future__ import annotations

from django.contrib import admin

from sandbox.audit.models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("occurred_at", "action", "actor", "object_type", "correlation_id")
    list_filter = ("action", "object_type")
    search_fields = ("action", "object_external_id", "correlation_id")
    date_hierarchy = "occurred_at"

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
