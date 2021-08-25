import datetime

from django.contrib import admin, messages
from django.contrib.gis import forms as gis_forms
from django.contrib.gis.db import models as gis_models
from django.urls import reverse
from django.utils.safestring import mark_safe

from itou.siaes import models
from itou.siaes.admin_forms import SiaeAdminForm
from itou.utils.organizations.admin import HasMembersFilter, MembersInline, OrganizationAdmin


class SiaeMembersInline(MembersInline):
    model = models.Siae.members.through


class JobsInline(admin.TabularInline):
    model = models.Siae.jobs.through
    extra = 1
    raw_id_fields = ("appellation",)


class FinancialAnnexesInline(admin.TabularInline):
    model = models.SiaeFinancialAnnex
    fields = ("number", "state", "start_at", "end_at", "is_active")
    readonly_fields = ("number", "state", "start_at", "end_at", "is_active")
    can_delete = False

    ordering = ("-number",)

    def is_active(self, obj):
        return obj.is_active

    is_active.boolean = True
    is_active.short_description = "Active"

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request, obj=None):
        return False


class SiaesInline(admin.TabularInline):
    model = models.Siae
    fields = ("siae_id_link", "kind", "siret", "source", "name", "brand")
    readonly_fields = ("siae_id_link", "kind", "siret", "source", "name", "brand")
    can_delete = False

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request, obj=None):
        return False

    def siae_id_link(self, obj):
        app_label = obj._meta.app_label
        model_name = obj._meta.model_name
        url = reverse(f"admin:{app_label}_{model_name}_change", args=[obj.id])
        return mark_safe(f'<a href="{url}">{obj.id}</a>')


@admin.register(models.Siae)
class SiaeAdmin(OrganizationAdmin):
    form = SiaeAdminForm
    list_display = ("pk", "siret", "kind", "name", "department", "geocoding_score", "member_count", "created_at")
    list_filter = (HasMembersFilter, "kind", "block_job_applications", "source", "department")
    raw_id_fields = ("created_by", "convention")
    readonly_fields = (
        "pk",
        "source",
        "created_by",
        "created_at",
        "updated_at",
        "job_applications_blocked_at",
        "geocoding_score",
    )
    fieldsets = (
        (
            "SIAE",
            {
                "fields": (
                    "pk",
                    "siret",
                    "naf",
                    "kind",
                    "name",
                    "brand",
                    "phone",
                    "email",
                    "auth_email",
                    "website",
                    "description",
                    "source",
                    "convention",
                    "created_by",
                    "created_at",
                    "updated_at",
                    "block_job_applications",
                    "job_applications_blocked_at",
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
    )
    search_fields = ("pk", "siret", "name", "city", "department", "post_code", "address_line_1")
    inlines = (SiaeMembersInline, JobsInline)
    formfield_overrides = {
        # https://docs.djangoproject.com/en/2.2/ref/contrib/gis/forms-api/#widget-classes
        gis_models.PointField: {"widget": gis_forms.OSMWidget(attrs={"map_width": 800, "map_height": 500})}
    }

    def get_queryset(self, request):
        # OrganizationAdmin adds some useful annotations.
        return super().get_queryset(request)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
            obj.source = models.Siae.SOURCE_STAFF_CREATED
            if not obj.geocoding_score and obj.geocoding_address:
                # Set geocoding.
                obj.set_coords(obj.geocoding_address, post_code=obj.post_code)

        if change and form.cleaned_data.get("extra_field_refresh_geocoding") and obj.geocoding_address:
            # Refresh geocoding.
            obj.set_coords(obj.geocoding_address, post_code=obj.post_code)

        # Pulled-up the save action:
        # many-to-many relationships / cross-tables references
        # have to be saved before using them
        super().save_model(request, obj, form, change)

        if obj.members.count() == 0 and not obj.auth_email:
            messages.warning(
                request,
                (
                    "Cette structure sans membre n'ayant pas d'email "
                    "d'authentification il est impossible de s'y inscrire."
                ),
            )


@admin.register(models.SiaeJobDescription)
class SiaeJobDescription(admin.ModelAdmin):
    list_display = ("appellation", "siae", "created_at", "updated_at", "is_active", "custom_name")
    raw_id_fields = ("appellation", "siae")


@admin.register(models.SiaeConvention)
class SiaeConvention(admin.ModelAdmin):
    list_display = ("kind", "siret_signature", "is_active")
    list_filter = ("kind", "is_active")
    raw_id_fields = ("reactivated_by",)
    readonly_fields = (
        "kind",
        "siret_signature",
        "deactivated_at",
        "reactivated_by",
        "reactivated_at",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (
            "Informations",
            {
                "fields": (
                    "kind",
                    "siret_signature",
                )
            },
        ),
        (
            "Statut",
            {
                "fields": (
                    "is_active",
                    "deactivated_at",
                    "reactivated_by",
                    "reactivated_at",
                )
            },
        ),
        (
            "Autres",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )
    search_fields = ("pk", "siret_signature")
    inlines = (FinancialAnnexesInline, SiaesInline)

    def save_model(self, request, obj, form, change):
        if change:
            old_obj = self.model.objects.get(id=obj.id)
            if obj.is_active and not old_obj.is_active:
                # Itou staff manually reactivated convention.
                obj.reactivated_by = request.user
                obj.reactivated_at = datetime.datetime.now()
            if not obj.is_active and old_obj.is_active:
                # Itou staff manually deactivated convention.
                # Start grace period.
                obj.deactivated_at = datetime.datetime.now()
        super().save_model(request, obj, form, change)


@admin.register(models.SiaeFinancialAnnex)
class SiaeFinancialAnnex(admin.ModelAdmin):
    list_display = ("number", "state", "start_at", "end_at")
    list_filter = ("state",)
    raw_id_fields = ("convention",)
    readonly_fields = (
        "number",
        "state",
        "start_at",
        "end_at",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (
            "Informations",
            {
                "fields": (
                    "number",
                    "convention",
                )
            },
        ),
        (
            "Statut",
            {
                "fields": (
                    "state",
                    "start_at",
                    "end_at",
                )
            },
        ),
        (
            "Autres",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )
    search_fields = ("pk", "number")
