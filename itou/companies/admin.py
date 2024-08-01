from django.contrib import admin, messages
from django.contrib.admin.utils import display_for_value
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from itou.approvals.models import Approval
from itou.common_apps.organizations.admin import HasMembersFilter, MembersInline, OrganizationAdmin
from itou.companies import enums, models
from itou.companies.admin_forms import CompanyAdminForm
from itou.utils.admin import (
    ItouGISMixin,
    ItouModelAdmin,
    ItouTabularInline,
    PkSupportRemarkInline,
    get_admin_view_link,
)
from itou.utils.apis.exceptions import GeocodingDataError
from itou.utils.export import to_streaming_response
from itou.utils.urls import add_url_params


class CompanyMembersInline(MembersInline):
    model = models.Company.members.through
    readonly_fields = ("is_active", "created_at", "updated_at", "updated_by", "joined_at", "notifications")
    raw_id_fields = ("user",)


class JobsInline(ItouTabularInline):
    model = models.Company.jobs.through
    extra = 1
    fields = (
        "jobdescription_id_link",
        "appellation",
        "custom_name",
        "created_at",
        "contract_type",
    )
    raw_id_fields = ("appellation", "company", "location")
    readonly_fields = (
        "appellation",
        "custom_name",
        "contract_type",
        "created_at",
        "updated_at",
        "jobdescription_id_link",
    )

    @admin.display(description="lien vers la fiche de poste")
    def jobdescription_id_link(self, obj):
        return get_admin_view_link(obj, content=format_html("<strong>Fiche de poste ID: {}</strong>", obj.id))


class FinancialAnnexesInline(ItouTabularInline):
    model = models.SiaeFinancialAnnex
    fields = ("number", "is_active", "state", "start_at", "end_at", "created_at")
    readonly_fields = ("number", "is_active", "state", "start_at", "end_at", "created_at")
    can_delete = False

    ordering = (
        "-end_at",
        "-start_at",
        "-number",
    )

    @admin.display(boolean=True, description="active")
    def is_active(self, obj):
        return obj.is_active

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request, obj=None):
        return False


class CompaniesInline(ItouTabularInline):
    model = models.Company
    fields = ("company_id_link", "kind", "siret", "source", "name", "brand")
    readonly_fields = ("company_id_link", "kind", "siret", "source", "name", "brand")
    can_delete = False

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request, obj=None):
        return False

    def company_id_link(self, obj):
        return get_admin_view_link(obj)


def _companies_serializer(queryset):
    tz = timezone.get_current_timezone()
    return [
        (
            company.siret,
            company.name,
            company.address_on_one_line,
            company.created_by.last_name if company.created_by else "",
            company.created_by.first_name if company.created_by else "",
            company.created_by.phone if company.created_by else "",
            company.created_by.email if company.created_by else "",
            company.created_at.astimezone(tz).strftime("%Y/%m/%d %H:%M"),
        )
        for company in queryset
    ]


@admin.register(models.Company)
class CompanyAdmin(ItouGISMixin, OrganizationAdmin):
    @admin.action(description="Exporter les entreprises selectionnées")
    def export(self, request, queryset):
        export_qs = queryset.select_related("created_by")
        headers = [
            "SIRET",
            "Nom",
            "Adresse complète",
            "Nom",
            "Prénom",
            "Téléphone",
            "Adresse e-mail",
            "Date de création",
        ]

        return to_streaming_response(
            export_qs,
            "entreprises",
            headers,
            _companies_serializer,
            with_time=True,
        )

    form = CompanyAdminForm
    list_display = ("pk", "siret", "kind", "name", "department", "geocoding_score", "member_count", "created_at")
    list_filter = (HasMembersFilter, "kind", "block_job_applications", "source", "department")
    raw_id_fields = ("created_by", "convention")
    fieldsets = (
        (
            "Entreprise",
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
                    "provided_support",
                    "source",
                    "convention",
                    "created_by",
                    "created_at",
                    "updated_at",
                    "block_job_applications",
                    "job_applications_blocked_at",
                    "approvals_list",
                    "rdv_insertion_id",
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
    inlines = (CompanyMembersInline, JobsInline, PkSupportRemarkInline)
    actions = [export]

    def get_export_filename(self, request, queryset, file_format):
        return f"Entreprises-{timezone.now():%Y-%m-%d}.{file_format.get_extension()}"

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = [
            "pk",
            "source",
            "created_by",
            "created_at",
            "updated_at",
            "job_applications_blocked_at",
            "geocoding_score",
            "approvals_list",
        ]
        if obj:
            readonly_fields.append("kind")
        return readonly_fields

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
            obj.source = models.Company.SOURCE_STAFF_CREATED
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

    def has_delete_permission(self, request, obj=None):
        if obj and obj.siret == enums.POLE_EMPLOI_SIRET:
            return False
        return super().has_delete_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        # we specifically target Pole Emploi and not a "RESERVED" kind nor the "ADMIN_CREATED" source.
        # The reason behind this is that at the time of writing, what we want to avoid is to modify
        # Pole Emploi in the admin; we can't make assumptions about the future ADMIN_CREATED or
        # RESERVED Companies that might be created someday.
        if obj and obj.siret == enums.POLE_EMPLOI_SIRET:
            return False
        return super().has_change_permission(request, obj)

    @admin.display(description="Liste des PASS IAE pour cette entreprise")
    def approvals_list(self, obj):
        if obj.pk is None:
            return self.get_empty_value_display()
        url = add_url_params(reverse("admin:approvals_approval_changelist"), {"assigned_company": obj.id, "o": -6})
        count = Approval.objects.is_assigned_to(obj.id).count()
        valid_count = Approval.objects.is_assigned_to(obj.id).valid().count()
        return format_html('<a href="{}">Liste des {} Pass IAE (dont {} valides)</a>', url, count, valid_count)


@admin.register(models.JobDescription)
class JobDescriptionAdmin(ItouModelAdmin):
    list_display = (
        "display_name",
        "company",
        "contract_type",
        "created_at",
        "updated_at",
        "is_active",
        "open_positions",
    )
    raw_id_fields = ("appellation", "company", "location")
    list_filter = ("source_kind",)
    search_fields = (
        "pk",
        "company__siret",
        "company__name",
        "custom_name",
        "appellation__name",
    )
    readonly_fields = (
        "pk",
        "source_id",
        "source_kind",
        "source_url",
        "field_history",
    )

    @admin.display(description="Intitulé du poste")
    def display_name(self, obj):
        return obj.custom_name if obj.custom_name else obj.appellation


@admin.register(models.SiaeConvention)
class SiaeConventionAdmin(ItouModelAdmin):
    list_display = ("kind", "siret_signature", "is_active")
    list_filter = ("kind", "is_active")
    raw_id_fields = ("reactivated_by",)
    readonly_fields = (
        "asp_id",
        "kind",
        "siret_signature",
        "deactivated_at",
        "grace_period_end_at",
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
                    "asp_id",
                )
            },
        ),
        (
            "Statut",
            {
                "fields": (
                    "is_active",
                    "deactivated_at",
                    "grace_period_end_at",
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
    search_fields = ("pk", "siret_signature", "asp_id")
    inlines = (FinancialAnnexesInline, CompaniesInline, PkSupportRemarkInline)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        if change:
            old_obj = self.model.objects.get(id=obj.id)
            if obj.is_active and not old_obj.is_active:
                # Itou staff manually reactivated convention.
                obj.reactivated_by = request.user
                obj.reactivated_at = timezone.now()
            if not obj.is_active and old_obj.is_active:
                # Itou staff manually deactivated convention.
                # Start grace period.
                obj.deactivated_at = timezone.now()
        super().save_model(request, obj, form, change)

    @admin.display(description="fin de délai de grâce")
    def grace_period_end_at(self, obj):
        if not obj.deactivated_at:
            return self.get_empty_value_display()
        return display_for_value(
            obj.deactivated_at + timezone.timedelta(days=models.SiaeConvention.DEACTIVATION_GRACE_PERIOD_IN_DAYS),
            empty_value_display=self.get_empty_value_display(),
        )


@admin.register(models.SiaeFinancialAnnex)
class SiaeFinancialAnnexAdmin(ItouModelAdmin):
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

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
