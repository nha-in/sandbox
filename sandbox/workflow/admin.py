"""Read-only admin: the transition log is evidence, so nothing here may edit it."""

from __future__ import annotations

from django.contrib import admin

from sandbox.workflow.models import WorkflowReview
from sandbox.workflow.models import WorkflowTransition


@admin.register(WorkflowTransition)
class WorkflowTransitionAdmin(admin.ModelAdmin):
    list_display = ("created_date", "application", "from_state", "to_state", "actor")
    list_filter = ("action", "to_state")
    search_fields = ("application__reference",)
    date_hierarchy = "created_date"

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(WorkflowReview)
class WorkflowReviewAdmin(admin.ModelAdmin):
    list_display = ("decided_at", "application", "round", "decision", "reviewer")
    list_filter = ("decision",)
    search_fields = ("application__reference",)
    readonly_fields = ("decided_at",)
