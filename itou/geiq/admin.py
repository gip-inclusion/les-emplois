import logging

from django.contrib import admin, messages
from django.core.exceptions import ImproperlyConfigured
from django.utils.html import format_html

from itou.utils.admin import (
    ItouModelAdmin,
    ItouTabularInline,
    PkSupportRemarkInline,
    ReadonlyMixin,
    get_admin_view_link,
)
from itou.utils.apis import geiq_label

from . import models, sync


logger = logging.getLogger(__name__)


class ImplementationAssessmentInline(ItouTabularInline):
    model = models.ImplementationAssessment
    fields = ("id_link", "submitted_at", "reviewed_at")
    readonly_fields = ("id_link", "submitted_at", "reviewed_at")
    extra = 0

    @admin.display(description="lien vers les Siaes évaluées")
    def id_link(self, obj):
        return get_admin_view_link(obj, content=format_html("<strong>{}</strong>", obj))

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("campaign", "company")

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(models.ImplementationAssessmentCampaign)
class ImplementationAssessmentCampaignAdmin(ItouModelAdmin):
    @admin.action(description="Synchroniser les bilans des campagnes sélectionnées")
    def sync_assessments(self, request, queryset):
        for campaign in queryset:
            try:
                creates, updates, deletes = sync.sync_assessments(campaign)
            except ImproperlyConfigured:
                messages.error(request, "Synchronisation impossible avec Label: configuration incomplète")
                return
            except geiq_label.LabelAPIError:
                logger.warning("Error while syncing GEIQ campaign %s with Label", campaign)
                messages.error(request, f"Erreur lors de la synchronisation de la campagne {campaign} avec Label")
            else:
                messages.success(request, f"Les bilans de l’année {campaign.year} ont été synchronisés.")
                if nb_create := len(creates):
                    s = "s" if nb_create > 1 else ""
                    messages.success(request, f"{nb_create} bilan{s} créé{s}.")
                if nb_update := len(updates):
                    s = "s" if nb_update > 1 else ""
                    messages.success(request, f"{nb_update} bilan{s} mis à jour.")
                if nb_delete := len(deletes):
                    s = "s" if nb_delete > 1 else ""
                    messages.warning(request, f"{nb_delete} bilan{s} sont liés à des GEIQ n’existant plus dans LABEL.")

    actions = [sync_assessments]
    list_display = (
        "pk",
        "year",
        "submission_deadline",
        "review_deadline",
    )
    inlines = [
        ImplementationAssessmentInline,
        PkSupportRemarkInline,
    ]

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return self.readonly_fields + ("year",)
        return self.readonly_fields


@admin.register(models.ImplementationAssessment)
class ImplementationAssessmentAdmin(ReadonlyMixin, ItouModelAdmin):
    list_display = (
        "pk",
        "company",
        "campaign_year",
        "submitted_at",
        "reviewed_at",
    )
    list_filter = ("campaign__year",)

    @admin.display(description="Année de la campagne")
    def campaign_year(self, obj):
        return obj.campaign.year

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("campaign")


@admin.register(models.Employee)
class EmployeeAdmin(ReadonlyMixin, ItouModelAdmin):
    list_display = (
        "pk",
        "assessment",
        "last_name",
        "first_name",
    )


@admin.register(models.EmployeeContract)
class EmployeeContractAdmin(ReadonlyMixin, ItouModelAdmin):
    list_display = (
        "pk",
        "employee",
        "start_at",
        "end_at",
        "planned_end_at",
    )


@admin.register(models.EmployeePrequalification)
class EmployeePrequalificationAdmin(ReadonlyMixin, ItouModelAdmin):
    list_display = (
        "pk",
        "employee",
        "start_at",
        "end_at",
    )
