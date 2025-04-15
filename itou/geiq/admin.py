import logging

from django.contrib import admin
from django.utils.html import format_html

from itou.geiq import models
from itou.utils.admin import (
    ItouModelAdmin,
    ItouTabularInline,
    PkSupportRemarkInline,
    ReadonlyMixin,
    get_admin_view_link,
)


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
