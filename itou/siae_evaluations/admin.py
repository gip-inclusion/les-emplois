from django.contrib import admin

from itou.siae_evaluations import models


@admin.register(models.EvaluationCampaign)
class EvaluationCampaignAdmin(admin.ModelAdmin):
    list_display = ("name", "institution", "chosen_percent", "created_at", "ended_at")
    list_display_links = ("name",)
    readonly_fields = ("created_at",)
    raw_id_fields = ("institution",)
