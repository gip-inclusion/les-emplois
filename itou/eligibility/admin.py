from django.contrib import admin

from itou.eligibility import models


@admin.register(models.EligibilityDiagnosis)
class EligibilityAdmin(admin.ModelAdmin):
    list_display = ("id", "job_seeker", "author", "author_kind", "created_at")
    list_display_links = ("id", "job_seeker")
    list_filter = ("author_kind",)
    raw_id_fields = ("job_seeker", "author_siae", "author_prescriber_organization")
    readonly_fields = ("created_at", "updated_at")
