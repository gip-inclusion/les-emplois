from django.contrib import admin
from django.contrib.gis import forms as gis_forms
from django.contrib.gis.db import models as gis_models
from django.db.models import Count

from itou.institutions import models
from itou.institutions.admin_forms import InstitutionAdminForm


class MembersInline(admin.TabularInline):
    model = models.InstitutionMembership
    extra = 1
    raw_id_fields = ("user",)
    readonly_fields = ("is_active", "created_at", "updated_at", "updated_by", "joined_at")


@admin.register(models.Institution)
class InstitutionAdmin(admin.ModelAdmin):

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
    inlines = (MembersInline,)
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
    formfield_overrides = {
        # https://docs.djangoproject.com/en/2.2/ref/contrib/gis/forms-api/#widget-classes
        gis_models.PointField: {"widget": gis_forms.OSMWidget(attrs={"map_width": 800, "map_height": 500})}
    }

    def member_count(self, obj):
        return obj._member_count

    member_count.admin_order_field = "_member_count"

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.annotate(_member_count=Count("members", distinct=True))
        return queryset

    def save_model(self, request, obj, form, change):
        if not change:
            if not obj.geocoding_score and obj.geocoding_address:
                # Set geocoding.
                obj.set_coords(obj.geocoding_address, post_code=obj.post_code)

        if change and form.cleaned_data.get("extra_field_refresh_geocoding") and obj.geocoding_address:
            # Refresh geocoding.
            obj.set_coords(obj.geocoding_address, post_code=obj.post_code)

        super().save_model(request, obj, form, change)
