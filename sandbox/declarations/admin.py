"""Read-only: `services.py` is the only writer, and documents never render here.

The admin shows a document's metadata and fingerprint but offers no link to its
contents — downloads go through the org-scoped presigned view or nowhere.
"""

from __future__ import annotations

from django.contrib import admin

from sandbox.declarations.models import Declaration
from sandbox.declarations.models import DeclarationDocument
from sandbox.declarations.models import DeclarationMilestone


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class DeclarationMilestoneInline(admin.TabularInline):
    model = DeclarationMilestone
    fk_name = "declaration"
    extra = 0
    fields = ["milestone", "kind", "superseded_by", "created_date"]
    readonly_fields = ["milestone", "kind", "superseded_by", "created_date"]

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Declaration)
class DeclarationAdmin(ReadOnlyAdmin):
    list_display = ["external_id", "application", "kind", "state", "created_date"]
    list_filter = ["kind", "state"]
    search_fields = ["application__reference"]
    inlines = [DeclarationMilestoneInline]


@admin.register(DeclarationDocument)
class DeclarationDocumentAdmin(ReadOnlyAdmin):
    list_display = ["filename", "declaration", "content_type", "size", "sha256"]
    search_fields = ["filename", "sha256"]
