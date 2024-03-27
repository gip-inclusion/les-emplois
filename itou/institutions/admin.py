from django.contrib import admin, messages

from itou.common_apps.organizations.admin import MembersInline, OrganizationAdmin
from itou.institutions import models
from itou.institutions.admin_forms import InstitutionAdminForm
from itou.utils.admin import ItouGISMixin
from itou.utils.apis.exceptions import GeocodingDataError


class InstitutionMembersInline(MembersInline):
    model = models.InstitutionMembership


@admin.register(models.Institution)
class InstitutionAdmin(ItouGISMixin, OrganizationAdmin):
    form = InstitutionAdminForm
    fieldsets = (
        (
            "Structure",
            {
                "fields": (
                    "pk",
                    "kind",
                    "name",
                )
            },
        ),
        (
            "Adresse",
            {
                "fields": (
                    "address_line_1",
                    "address_line_2",
                    "post_code",
                    "city",
                    "department",
                    "extra_field_refresh_geocoding",
                    "coords",
                    "geocoding_score",
                )
            },
        ),
        (
            "Info",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )
    inlines = (InstitutionMembersInline,)
    list_display = ("pk", "name", "kind", "post_code", "city", "department", "member_count")
    list_display_links = ("pk", "name")
    list_filter = (
        "kind",
        "department",
    )
    readonly_fields = (
        "pk",
        "created_at",
        "updated_at",
        "geocoding_score",
    )
    search_fields = (
        "pk",
        "name",
        "department",
        "post_code",
        "city",
    )

    def save_model(self, request, obj, form, change):
        if not change:
            if not obj.geocoding_score and obj.geocoding_address:
                try:
                    # Set geocoding.
                    obj.geocode_address()
                except GeocodingDataError:
                    # do nothing, the user has not made any changes to the address
                    pass

        if change and form.cleaned_data.get("extra_field_refresh_geocoding") and obj.geocoding_address:
            try:
                # Refresh geocoding.
                obj.geocode_address()
            except GeocodingDataError:
                messages.error(request, "L'adresse semble erronée car le geocoding n'a pas pu être recalculé.")

        super().save_model(request, obj, form, change)
