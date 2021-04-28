from django.contrib import admin
from django.contrib.gis import forms as gis_forms
from django.contrib.gis.db import models as gis_models
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.utils.timezone import now

from itou.prescribers import models
from itou.prescribers.admin_forms import PrescriberOrganizationAdminForm


class TmpMissingSiretFilter(admin.SimpleListFilter):
    """
    Temporary filter to list organizations without SIRET (except Pôle emploi).
    They were created prior to the new Prescriber's signup process.
    Delete this filter when all SIRETs are filled in.
    """

    title = "SIRET à renseigner"
    parameter_name = "missing_siret"

    def lookups(self, request, model_admin):
        return (("yes", "Oui"),)

    def queryset(self, request, queryset):
        value = self.value()
        if value == "yes":
            return (
                queryset.exclude(kind=models.PrescriberOrganization.Kind.PE.value)
                .exclude(members=None)
                .filter(siret__isnull=True)
            )
        return queryset


class TmpCanBeDeletedFilter(admin.SimpleListFilter):
    """
    Temporary filter to list organizations without members (except Pôle emploi).
    They were created by us prior to the new Prescriber's signup process based
    on various sources of data and assumptions.
    Delete this filter when they are all deleted.
    """

    title = "Sans membres à supprimer"
    parameter_name = "missing_members"

    def lookups(self, request, model_admin):
        return (("yes", "Oui"),)

    def queryset(self, request, queryset):
        value = self.value()
        if value == "yes":
            return queryset.filter(members=None).exclude(kind=models.PrescriberOrganization.Kind.PE.value)
        return queryset


class HasMembersFilter(admin.SimpleListFilter):
    title = "A des membres"
    parameter_name = "has_members"

    def lookups(self, request, model_admin):
        return (("yes", "Oui"), ("no", "Non"))

    def queryset(self, request, queryset):
        value = self.value()
        if value == "yes":
            return queryset.filter(_member_count__gt=0)
        if value == "no":
            return queryset.exclude(_member_count__gt=0)
        return queryset


class AuthorizationValidationRequired(admin.SimpleListFilter):
    title = "Validation de l'habilitation requise"
    parameter_name = "authorization_validation_required"

    def lookups(self, request, model_admin):
        return (("required", "Requise"),)

    def queryset(self, request, queryset):
        if self.value() == "required":
            return queryset.filter(
                authorization_status=models.PrescriberOrganization.AuthorizationStatus.NOT_SET, _member_count__gt=0
            )
        return queryset


class MembersInline(admin.TabularInline):
    model = models.PrescriberOrganization.members.through
    extra = 1
    raw_id_fields = ("user",)
    readonly_fields = ("is_active", "created_at", "updated_at", "updated_by")


@admin.register(models.PrescriberOrganization)
class PrescriberOrganizationAdmin(admin.ModelAdmin):
    class Media:
        css = {"all": ("css/itou-admin.css",)}

    form = PrescriberOrganizationAdminForm
    change_form_template = "admin/prescribers/change_form.html"
    fieldsets = (
        (
            "Structure",
            {
                "fields": (
                    "pk",
                    "siret",
                    "kind",
                    "is_brsa",
                    "name",
                    "phone",
                    "email",
                    "code_safir_pole_emploi",
                    "is_authorized",
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
                    "created_by",
                    "created_at",
                    "updated_at",
                    "authorization_status",
                    "authorization_updated_at",
                    "authorization_updated_by",
                )
            },
        ),
    )
    inlines = (MembersInline,)
    list_display = ("pk", "siret", "name", "kind", "post_code", "city", "department", "is_authorized", "member_count")
    list_display_links = ("pk", "name")
    list_filter = (
        AuthorizationValidationRequired,
        TmpMissingSiretFilter,
        TmpCanBeDeletedFilter,
        HasMembersFilter,
        "is_authorized",
        "kind",
        "department",
    )
    raw_id_fields = ("created_by",)
    readonly_fields = (
        "pk",
        "created_by",
        "created_at",
        "updated_at",
        "is_authorized",
        "authorization_status",
        "authorization_updated_at",
        "authorization_updated_by",
        "geocoding_score",
    )
    search_fields = (
        "pk",
        "siret",
        "name",
        "code_safir_pole_emploi",
        "city",
        "department",
        "post_code",
        "address_line_1",
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
            obj.created_by = request.user
            if not obj.geocoding_score and obj.geocoding_address:
                # Set geocoding.
                obj.set_coords(obj.geocoding_address, post_code=obj.post_code)

        if change and form.cleaned_data.get("extra_field_refresh_geocoding") and obj.geocoding_address:
            # Refresh geocoding.
            obj.set_coords(obj.geocoding_address, post_code=obj.post_code)

        super().save_model(request, obj, form, change)

    def response_change(self, request, obj):
        """
        Override to add custom "actions" in `self.change_form_template` for:
        * refusing authorization
        * validating authorization
        """
        if "_authorization_action_refuse" in request.POST:
            # Same checks in change_form template to display the button
            if request.user.is_superuser or obj.has_pending_authorization():
                obj.is_authorized = False
                obj.authorization_status = models.PrescriberOrganization.AuthorizationStatus.REFUSED
                obj.authorization_updated_at = now()
                obj.authorization_updated_by = request.user
                obj.save()
                obj.refused_prescriber_organization_email().send()
            else:
                return PermissionDenied()

        if "_authorization_action_validate" in request.POST:
            # Same checks as change_form template to display the button
            if request.user.is_superuser or obj.has_pending_authorization() or obj.has_refused_authorization():
                obj.is_authorized = True
                obj.authorization_status = models.PrescriberOrganization.AuthorizationStatus.VALIDATED
                obj.authorization_updated_at = now()
                obj.authorization_updated_by = request.user
                obj.save()
                obj.validated_prescriber_organization_email().send()
            else:
                raise PermissionDenied()

        return super().response_change(request, obj)
