from __future__ import annotations

from django.contrib import admin

from sandbox.catalog.models import Milestone


@admin.register(Milestone)
class MilestoneAdmin(admin.ModelAdmin):
    list_display = ["title", "key", "track", "order", "is_active"]
    list_filter = ["track", "is_active"]
    search_fields = ["title", "key"]
    ordering = ["track", "order"]
    readonly_fields = ["external_id", "created_date", "modified_date"]
