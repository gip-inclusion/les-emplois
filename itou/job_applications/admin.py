from django.contrib import admin

from itou.job_applications import models


class JobsInline(admin.TabularInline):
    model = models.JobApplication.jobs.through
    extra = 1
    raw_id_fields = ("appellation",)


@admin.register(models.JobApplication)
class JobApplicationAdmin(admin.ModelAdmin):
    list_display = ("id", "job_seeker", "prescriber_user", "siae", "created_at")
    raw_id_fields = ("job_seeker", "siae", "prescriber_user", "prescriber", "jobs")
    list_filter = ("state",)
    read_only_fields = ("created_at", "updated_at")
    inlines = (JobsInline,)


@admin.register(models.JobApplicationTransitionLog)
class JobApplicationTransitionLogAdmin(admin.ModelAdmin):
    actions = None
    date_hierarchy = "timestamp"
    list_display = (
        "job_application",
        "transition",
        "from_state",
        "to_state",
        "user",
        "timestamp",
    )
    list_filter = ("transition",)
    raw_id_fields = ("job_application", "user")
    read_only_fields = (
        "user",
        "modified_object",
        "transition",
        "timestamp",
        "source_ip",
    )
    search_fields = ("transition", "user__username")
