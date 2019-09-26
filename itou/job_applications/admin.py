from django.contrib import admin

from itou.job_applications import models


class TransitionLogInline(admin.TabularInline):
    model = models.JobApplicationTransitionLog
    extra = 0
    raw_id_fields = ("user",)
    can_delete = False
    readonly_fields = ("transition", "from_state", "to_state", "user", "timestamp")

    def has_add_permission(self, request):
        return False


class JobsInline(admin.TabularInline):
    model = models.JobApplication.jobs.through
    extra = 1
    raw_id_fields = ("appellation",)


@admin.register(models.JobApplication)
class JobApplicationAdmin(admin.ModelAdmin):
    list_display = ("id", "job_seeker", "prescriber", "siae", "created_at")
    raw_id_fields = (
        "job_seeker",
        "siae",
        "prescriber",
        "prescriber_organization",
        "jobs",
    )
    list_filter = ("state",)
    readonly_fields = ("created_at", "updated_at")
    inlines = (JobsInline, TransitionLogInline)


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
    readonly_fields = (
        "job_application",
        "transition",
        "from_state",
        "to_state",
        "user",
        "timestamp",
    )
    search_fields = ("transition", "user__username")
