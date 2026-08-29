from __future__ import annotations

from django.contrib import admin

from sandbox.organisations.models import Membership
from sandbox.organisations.models import Organisation
from sandbox.organisations.models import Product


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    autocomplete_fields = ["user"]
    readonly_fields = ["external_id", "created_date"]


@admin.register(Organisation)
class OrganisationAdmin(admin.ModelAdmin):
    list_display = ["name", "kind", "ownership", "category", "verification_state"]
    list_filter = ["kind", "ownership", "category", "verification_state"]
    search_fields = ["name", "slug", "gst_number"]
    readonly_fields = ["external_id", "created_date", "modified_date"]
    inlines = [MembershipInline]


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["name", "organisation", "created_date"]
    list_filter = ["organisation"]
    search_fields = ["name", "slug"]
    readonly_fields = ["external_id", "created_date", "modified_date"]


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ["user", "organisation", "role", "created_date"]
    list_filter = ["role"]
    search_fields = ["user__email", "organisation__name"]
    autocomplete_fields = ["user", "organisation"]
    readonly_fields = ["external_id", "created_date", "modified_date"]
