from django.contrib import admin, messages
from django.urls import reverse
from django.utils.safestring import mark_safe

from itou.siae_evaluations import models


class EvaluatedSiaesInline(admin.TabularInline):
    model = models.EvaluatedSiae
    fields = ("id_link", "reviewed_at", "state")
    readonly_fields = ("id_link", "reviewed_at", "state")
    extra = 0

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.prefetch_related(
            "evaluated_job_applications", "evaluated_job_applications__evaluated_administrative_criteria"
        )
        return queryset

    def state(self, obj):
        return obj.state

    def id_link(self, obj):
        app_label = obj._meta.app_label
        model_name = obj._meta.model_name
        url = reverse(f"admin:{app_label}_{model_name}_change", args=[obj.id])
        return mark_safe(f'<a href="{url}">Lien vers la Siae évaluée <strong>{obj}</strong></a>')

    id_link.short_description = "Lien vers les Siaes évaluées"


class EvaluatedJobApplicationsInline(admin.TabularInline):
    model = models.EvaluatedJobApplication
    fields = ("id_link", "approval", "job_seeker", "state")
    readonly_fields = ("id_link", "approval", "job_seeker", "state")
    extra = 0

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.prefetch_related("evaluated_administrative_criteria")
        return queryset

    def state(self, obj):
        return obj.state

    def id_link(self, obj):
        app_label = obj._meta.app_label
        model_name = obj._meta.model_name
        url = reverse(f"admin:{app_label}_{model_name}_change", args=[obj.id])
        return mark_safe(f'<a href="{url}">Lien vers la candidature évaluée <strong>{obj}</strong></a>')

    id_link.short_description = "Lien vers les candidatures évaluées"

    def approval(self, obj):
        if obj.job_application.approval:
            return obj.job_application.approval.number
        return "-"

    def job_seeker(self, obj):
        if obj.job_application.job_seeker:
            return obj.job_application.job_seeker
        return "-"


class EvaluatedAdministrativeCriteriaInline(admin.TabularInline):
    model = models.EvaluatedAdministrativeCriteria
    fields = ("id_link", "uploaded_at", "submitted_at", "review_state")
    readonly_fields = ("id_link", "uploaded_at", "submitted_at", "review_state")
    extra = 0

    def id_link(self, obj):
        app_label = obj._meta.app_label
        model_name = obj._meta.model_name
        url = reverse(f"admin:{app_label}_{model_name}_change", args=[obj.id])
        return mark_safe(f'<a href="{url}">Lien vers le critère administratif <strong>{obj}</strong></a>')

    id_link.short_description = "Lien vers les critères administratifs évalués"


@admin.register(models.EvaluationCampaign)
class EvaluationCampaignAdmin(admin.ModelAdmin):
    @admin.action(description="Passer les campagnes en phase contradictoire")
    def transition_to_adversarial_phase(self, request, queryset):
        for campaign in queryset:
            campaign.transition_to_adversarial_phase()

        messages.success(
            request,
            (
                "Les Siaes qui n'avaient pas encore transmis leurs justificatifs, "
                "sont passées en phase contradictoire pour les campagnes sélectionnées."
            ),
        )

    @admin.action(description="Clore les campagnes")
    def close(self, request, queryset):
        for campaign in queryset:
            campaign.close()

        messages.success(
            request,
            ("Les campagnes sélectionnées sont closes."),
        )

    actions = [transition_to_adversarial_phase, close]
    list_display = (
        "name",
        "institution",
        "evaluated_period_start_at",
        "evaluated_period_end_at",
        "chosen_percent",
        "created_at",
        "evaluations_asked_at",
        "ended_at",
    )
    list_display_links = ("name",)
    readonly_fields = (
        "institution",
        "evaluated_period_start_at",
        "evaluated_period_end_at",
        "chosen_percent",
        "created_at",
        "percent_set_at",
        "evaluations_asked_at",
        "ended_at",
    )
    list_filter = (
        "evaluations_asked_at",
        "ended_at",
        "institution__department",
    )
    inlines = [
        EvaluatedSiaesInline,
    ]


@admin.register(models.EvaluatedSiae)
class EvaluatedSiaeAdmin(admin.ModelAdmin):
    list_display = ("evaluation_campaign", "siae", "reviewed_at")
    list_display_links = ("siae",)
    readonly_fields = ("evaluation_campaign", "siae", "reviewed_at", "state")
    list_filter = (
        "reviewed_at",
        "evaluation_campaign__institution__department",
    )
    search_fields = ("siae__name",)
    inlines = [
        EvaluatedJobApplicationsInline,
    ]

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.prefetch_related(
            "evaluated_job_applications", "evaluated_job_applications__evaluated_administrative_criteria"
        )
        return queryset

    def state(self, obj):
        return obj.state


@admin.register(models.EvaluatedJobApplication)
class EvaluatedJobApplicationAdmin(admin.ModelAdmin):
    list_display = ("evaluated_siae", "job_application", "approval", "job_seeker")
    list_display_links = ("job_application",)
    readonly_fields = ("evaluated_siae", "job_application", "approval", "job_seeker", "state")
    inlines = [
        EvaluatedAdministrativeCriteriaInline,
    ]

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.prefetch_related("evaluated_administrative_criteria")
        return queryset

    def state(self, obj):
        return obj.state

    def approval(self, obj):
        if obj.job_application.approval:
            return obj.job_application.approval.number
        return "-"

    def job_seeker(self, obj):
        if obj.job_application.job_seeker:
            return obj.job_application.job_seeker
        return "-"


@admin.register(models.EvaluatedAdministrativeCriteria)
class EvaluatedAdministrativeCriteriaAdmin(admin.ModelAdmin):
    list_display = ("evaluated_job_application", "administrative_criteria", "submitted_at", "review_state")
    list_display_links = ("administrative_criteria",)
    readonly_fields = (
        "evaluated_job_application",
        "administrative_criteria",
        "uploaded_at",
        "proof_url",
        "submitted_at",
        "review_state",
    )
