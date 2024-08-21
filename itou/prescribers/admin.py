from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.utils.timezone import now

from itou.common_apps.organizations.admin import HasMembersFilter, MembersInline, OrganizationAdmin
from itou.prescribers.admin_forms import PrescriberOrganizationAdminForm
from itou.prescribers.enums import PrescriberAuthorizationStatus, PrescriberOrganizationKind
from itou.prescribers.models import PrescriberOrganization
from itou.utils.admin import ItouGISMixin, PkSupportRemarkInline
from itou.utils.apis.exceptions import GeocodingDataError


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
                queryset.exclude(kind=PrescriberOrganizationKind.PE.value)
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
            return queryset.filter(members=None).exclude(kind=PrescriberOrganizationKind.PE.value)
        return queryset


class AuthorizationValidationRequired(admin.SimpleListFilter):
    title = "Validation de l'habilitation requise"
    parameter_name = "authorization_validation_required"

    def lookups(self, request, model_admin):
        return (("required", "Requise"),)

    def queryset(self, request, queryset):
        if self.value() == "required":
            return queryset.filter(authorization_status=PrescriberAuthorizationStatus.NOT_SET, _member_count__gt=0)
        return queryset


class PrescriberOrganizationMembersInline(MembersInline):
    model = PrescriberOrganization.members.through


@admin.register(PrescriberOrganization)
class PrescriberOrganizationAdmin(ItouGISMixin, OrganizationAdmin):
    class Media:
        css = {"all": ("css/itou-admin.css",)}

    form = PrescriberOrganizationAdminForm
    change_form_template = "admin/prescribers/change_form.html"
    fieldsets = (
        (
            "Organisation",
            {
                "fields": (
                    "pk",
                    "siret",
                    "is_head_office",
                    "kind",
                    "is_brsa",
                    "name",
                    "phone",
                    "email",
                    "website",
                    "code_safir_pole_emploi",
                    "is_authorized",
                    "description",
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
    inlines = (
        PrescriberOrganizationMembersInline,
        PkSupportRemarkInline,
    )
    list_display = ("pk", "siret", "name", "kind", "post_code", "city", "department", "is_authorized", "member_count")
    list_display_links = ("pk", "name")
    list_filter = (
        AuthorizationValidationRequired,
        "is_head_office",
        TmpMissingSiretFilter,
        TmpCanBeDeletedFilter,
        HasMembersFilter,
        "is_authorized",
        "kind",
        "is_brsa",
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

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
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
                obj.authorization_status = PrescriberAuthorizationStatus.REFUSED
                obj.authorization_updated_at = now()
                obj.authorization_updated_by = request.user
                obj.kind = PrescriberOrganizationKind.OTHER
                obj.save()
                obj.refused_prescriber_organization_email().send()
            else:
                raise PermissionDenied()

        if "_authorization_action_validate" in request.POST:
            # Same checks as change_form template to display the button
            if request.user.is_superuser or obj.has_pending_authorization() or obj.has_refused_authorization():
                obj.is_authorized = True
                obj.authorization_status = PrescriberAuthorizationStatus.VALIDATED
                obj.authorization_updated_at = now()
                obj.authorization_updated_by = request.user
                obj.save()
                obj.validated_prescriber_organization_email().send()
            else:
                raise PermissionDenied()

        return super().response_change(request, obj)
