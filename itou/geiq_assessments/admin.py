import logging
from pprint import pformat

from django.contrib import admin, messages
from django.core.exceptions import ImproperlyConfigured
from django.utils.html import format_html

from itou.geiq import sync
from itou.geiq_assessments import models
from itou.utils.admin import (
    ItouModelAdmin,
    ItouTabularInline,
    PkSupportRemarkInline,
    ReadonlyMixin,
    get_admin_view_link,
)
from itou.utils.apis import geiq_label


logger = logging.getLogger(__name__)


@admin.register(models.AssessmentCampaign)
class AssessmentCampaignAdmin(ItouModelAdmin):
    @admin.action(description="Récupérer & stocker la liste des GEIQ avec leurs antennes")
    def download_label_infos(self, request, queryset):
        for campaign in queryset.select_related("label_infos"):
            if hasattr(campaign, "label_infos"):
                messages.error(request, f"Les informations label de la campagne {campaign} ont déjà été récupérées.")
                continue

            try:
                data = sync.get_geiq_infos()
                campaign.label_infos = models.LabelInfos.objects.create(campaign=campaign, data=data)
            except ImproperlyConfigured:
                messages.error(request, "Synchronisation impossible avec label: configuration incomplète")
                return

            except geiq_label.LabelAPIError:
                logger.warning("Error while syncing GEIQ campaign %s with label", campaign)

                messages.error(request, f"Erreur lors de la synchronisation de la campagne {campaign} avec label")

            else:
                messages.success(request, f"Les informations label de la campagne {campaign} ont été récupérées.")

    actions = [download_label_infos]
    fields = [
        "year",
        "submission_deadline",
        "review_deadline",
        "label_infos_link",
    ]
    readonly_fields = ("label_infos_link",)
    list_display = (
        "pk",
        "year",
        "submission_deadline",
        "review_deadline",
    )
    inlines = [
        PkSupportRemarkInline,
    ]

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return self.readonly_fields + ("year",)
        return self.readonly_fields

    @admin.display(description="données label")
    def label_infos_link(self, obj):
        return (
            get_admin_view_link(obj.label_infos, content=obj.label_infos.synced_at.isoformat())
            if hasattr(obj, "label_infos")
            else None
        )


@admin.register(models.LabelInfos)
class LABELInfosAdmin(ReadonlyMixin, ItouModelAdmin):
    fields = ["campaign", "synced_at", "pretty_data"]

    @admin.display(description="Données label")
    def pretty_data(self, obj):
        if obj.data:
            return format_html("<pre><code>{}</code></pre>", pformat(obj.data, width=200))

        return "-"


class AssessmentInstitutionLinkInline(ReadonlyMixin, ItouTabularInline):
    model = models.AssessmentInstitutionLink
    extra = 0
    show_change_link = True


class EmployeeInline(ReadonlyMixin, ItouTabularInline):
    model = models.Employee
    extra = 0
    show_change_link = True


class CompaniesInline(ReadonlyMixin, ItouTabularInline):
    model = models.Assessment.companies.through
    extra = 0
    show_change_link = True
    verbose_name_plural = "entreprises concernées"


@admin.register(models.Assessment)
class AssessmentAdmin(ReadonlyMixin, ItouModelAdmin):
    list_display = [
        "name_for_institution",
        "campaign",
        "created_at",
        "submitted_at",
        "reviewed_at",
        "dreets_reviewed_at",
    ]
    inlines = [
        AssessmentInstitutionLinkInline,
        CompaniesInline,
        EmployeeInline,
    ]
    fieldsets = (
        (
            "Bilan",
            {
                "fields": (
                    "pk",
                    "name_for_institution",
                    "created_at",
                    "created_by",
                    "campaign",
                    "companies",
                )
            },
        ),
        (
            "Données label",
            {
                "fields": (
                    "label_geiq_id",
                    "label_antennas",
                    "contracts_synced_at",
                    "summary_document_file",
                    "structure_financial_assessment_file",
                    "label_rates",
                    "employee_nb",
                )
            },
        ),
        (
            "Soumission GEIQ",
            {
                "fields": (
                    "action_financial_assessment_file",
                    "contracts_selection_validated_at",
                    "geiq_comment",
                    "submitted_at",
                    "submitted_by",
                )
            },
        ),
        (
            "Décision institution",
            {
                "fields": (
                    "grants_selection_validated_at",
                    "review_comment",
                    "convention_amount",
                    "granted_amount",
                    "advance_amount",
                    "decision_validated_at",
                    "reviewed_at",
                    "reviewed_by",
                    "dreets_reviewed_at",
                    "dreets_reviewed_by",
                )
            },
        ),
    )


class EmployeeContractInline(ReadonlyMixin, ItouTabularInline):
    model = models.EmployeeContract
    extra = 0
    show_change_link = True


class EmployeePrequalificationInline(ReadonlyMixin, ItouTabularInline):
    model = models.EmployeePrequalification
    extra = 0
    show_change_link = True


@admin.register(models.Employee)
class EmployeeAdmin(ReadonlyMixin, ItouModelAdmin):
    inlines = [
        EmployeeContractInline,
        EmployeePrequalificationInline,
    ]
    list_display = [
        "id",
        "assessment",
        "first_name",
        "last_name",
    ]


@admin.register(models.EmployeeContract)
class EmployeeContractAdmin(ReadonlyMixin, ItouModelAdmin):
    list_display = [
        "id",
        "employee",
        "start_at",
        "end_at",
        "planned_end_at",
    ]


@admin.register(models.EmployeePrequalification)
class EmployeePrequalificationAdmin(ReadonlyMixin, ItouModelAdmin):
    list_display = [
        "id",
        "employee",
        "start_at",
        "end_at",
    ]
