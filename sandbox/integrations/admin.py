"""Read-only ledger view: what exists in each external system, per application.

Nothing here may edit a row. The ledger is the idempotency backstop for B7's
chain — an operator correcting it by hand would let the chain create a duplicate
client, which is the exact legacy failure it exists to prevent.
"""

from __future__ import annotations

from django.contrib import admin

from sandbox.integrations.models import ProvisionedResource


@admin.register(ProvisionedResource)
class ProvisionedResourceAdmin(admin.ModelAdmin):
    list_display = (
        "created_date",
        "application",
        "system",
        "external_ref",
        "public_ref",
        "state",
    )
    list_filter = ("system", "state")
    search_fields = ("external_ref", "public_ref", "application__reference")
    list_select_related = ("application",)
    # `secret_ref` is a cache key to a live secret; it has no place on a screen.
    exclude = ("secret_ref",)

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
