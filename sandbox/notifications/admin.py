"""Read-only delivery log. Staff answer "did they get it?" here, and nothing
else: a log you can edit stops being evidence of what was sent."""

from __future__ import annotations

from django.contrib import admin

from sandbox.notifications.models import Message


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = (
        "created_date",
        "template_key",
        "recipient",
        "channel",
        "state",
        "attempts",
    )
    list_filter = ("state", "channel", "template_key")
    search_fields = ("recipient", "external_id", "provider_message_id")
    date_hierarchy = "created_date"
    list_select_related = ("application",)

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
