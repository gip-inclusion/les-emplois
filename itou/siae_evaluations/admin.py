from django.contrib import admin, messages
from django.utils import timezone

from itou.siae_evaluations import models


@admin.register(models.EvaluationCampaign)
class EvaluationCampaignAdmin(admin.ModelAdmin):

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
    readonly_fields = ("created_at",)
    raw_id_fields = ("institution",)


@admin.register(models.EvaluatedSiae)
class EvaluatedSiae(admin.ModelAdmin):
    list_display = (
        "evaluation_campaign",
        "siae",
    )
    list_display_links = (
        "evaluation_campaign",
        "siae",
    )
    raw_id_fields = (
        "siae",
        "evaluation_campaign",
    )


@admin.register(models.EvaluatedJobApplication)
class EvaluatedJobApplication(admin.ModelAdmin):
    list_display = ("evaluated_siae", "job_application")
    list_display_links = ("evaluated_siae", "job_application")
    raw_id_fields = (
        "job_application",
        "evaluated_siae",
    )


@admin.register(models.EvaluatedEligibilityDiagnosis)
class EvaluatedEligibilityDiagnosis(admin.ModelAdmin):
    list_display = ("evaluated_job_application", "administrative_criteria")
    list_display_links = ("evaluated_job_application", "administrative_criteria")
    readonly_fields = ("uploaded_at", "proof_url")
    raw_id_fields = (
        "evaluated_job_application",
        "administrative_criteria",
    )
