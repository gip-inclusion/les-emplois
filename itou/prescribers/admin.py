from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.utils.timezone import now

from itou.common_apps.organizations.admin import HasMembersFilter, MembersInline, OrganizationAdmin
from itou.prescribers.admin_forms import PrescriberOrganizationAdminForm
from itou.prescribers.enums import PrescriberAuthorizationStatus, PrescriberOrganizationKind
from itou.prescribers.models import PrescriberOrganization
from itou.utils.admin import CreatedOrUpdatedByMixin, ItouGISMixin, PkSupportRemarkInline
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
                queryset.exclude(kind=PrescriberOrganizationKind.FT.value)
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
            return queryset.filter(members=None).exclude(kind=PrescriberOrganizationKind.FT.value)
        return queryset


class IsAuthorizedFilter(admin.SimpleListFilter):
    title = "habilitation"
    parameter_name = "is_authorized"

    def lookups(self, request, model_admin):
        return (("yes", "Oui"), ("no", "Non"))

    def queryset(self, request, queryset):
        value = self.value()
        if value == "yes":
            return queryset.filter(authorization_status=PrescriberAuthorizationStatus.VALIDATED)
        if value == "no":
            return queryset.exclude(authorization_status=PrescriberAuthorizationStatus.VALIDATED)
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
    MEMBERSHIP_RO_LIMIT = 200

    def has_change_permission(self, request, obj=None):
        # A few organizations have more than 250 members, which causes the form
        # to have more than 1000 fields (the limit set in DATA_UPLOAD_MAX_NUMBER_FIELDS)
        # we believe that with 200+ members, there's no need to ask the support team to manually add a member
        return not bool(obj and obj.prescribermembership_set.count() > self.MEMBERSHIP_RO_LIMIT)


@admin.register(PrescriberOrganization)
class PrescriberOrganizationAdmin(ItouGISMixin, CreatedOrUpdatedByMixin, OrganizationAdmin):
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
                    "is_gps_authorized",
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
                    "automatic_geocoding_update",
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
        IsAuthorizedFilter,
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
            if not obj.geocoding_score and obj.geocoding_address:
                try:
                    # Set geocoding.
                    obj.geocode_address()
                except GeocodingDataError:
                    # do nothing, the user has not made any changes to the address
                    pass

        if change and form.cleaned_data.get("automatic_geocoding_update") and obj.geocoding_address:
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
            if request.user.is_itou_admin or obj.has_pending_authorization():
                if (
                    self.get_queryset(request)
                    .filter(siret=obj.siret, kind=PrescriberOrganizationKind.OTHER)
                    .exclude(pk=obj.pk)
                    .exists()
                ):
                    msg = (
                        "Impossible de refuser cette habilitation: cela changerait son type vers “Autre” "
                        "et une autre organisation de type “Autre” a le même SIRET."
                    )
                    self.message_user(request, msg, messages.ERROR)
                    return HttpResponseRedirect(request.get_full_path())
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
            if request.user.is_itou_admin or obj.has_pending_authorization() or obj.has_refused_authorization():
                # Organizations typed as "Other" cannot be marked valid
                if obj.kind == PrescriberOrganizationKind.OTHER:
                    msg = "Pour habiliter cette organisation, vous devez sélectionner un type différent de “Autre”."
                    self.message_user(request, msg, messages.ERROR)
                    return HttpResponseRedirect(request.get_full_path())
                obj.authorization_status = PrescriberAuthorizationStatus.VALIDATED
                obj.authorization_updated_at = now()
                obj.authorization_updated_by = request.user
                obj.save()
                obj.validated_prescriber_organization_email().send()
            else:
                raise PermissionDenied()

        return super().response_change(request, obj)

    @admin.display(description="Habilitation")
    def is_authorized(self, obj):
        return obj.is_authorized
