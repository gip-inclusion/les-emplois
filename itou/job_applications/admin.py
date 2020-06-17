from django.contrib import admin
from django.utils.translation import gettext as _

from itou.job_applications import models


class TransitionLogInline(admin.TabularInline):
    model = models.JobApplicationTransitionLog
    extra = 0
    raw_id_fields = ("user",)
    can_delete = False
    readonly_fields = ("transition", "from_state", "to_state", "user", "timestamp")

    def has_add_permission(self, request, obj=None):
        return False


class JobsInline(admin.TabularInline):
    model = models.JobApplication.selected_jobs.through
    extra = 1
    raw_id_fields = ("siaejobdescription",)


class ApprovalNumberSentByEmailFilter(admin.SimpleListFilter):
    title = _("PASS IAE envoyé par email")
    parameter_name = "approval_number_sent_by_email"

    def lookups(self, request, model_admin):
        return (("yes", _("Oui")), ("no", _("Non")))

    def queryset(self, request, queryset):
        value = self.value()
        if value == "yes":
            return queryset.exclude(approval=None).filter(approval_number_sent_by_email=True)
        if value == "no":
            return queryset.exclude(approval=None).filter(approval_number_sent_by_email=False)
        return queryset


@admin.register(models.JobApplication)
class JobApplicationAdmin(admin.ModelAdmin):
    actions = ("bulk_send_approval_by_email",)
    date_hierarchy = "created_at"
    list_display = ("id", "state", "sender_kind", "created_at")
    raw_id_fields = ("job_seeker", "sender", "sender_siae", "sender_prescriber_organization", "to_siae", "approval")
    exclude = ("selected_jobs",)
    list_filter = (
        ApprovalNumberSentByEmailFilter,
        "sender_kind",
        "state",
        "approval_delivery_mode",
        "sender_prescriber_organization__is_authorized",
        "to_siae__department",
    )
    readonly_fields = ("created_at", "updated_at", "approval_number_delivered_by")
    inlines = (JobsInline, TransitionLogInline)
    search_fields = ("to_siae__siret", "job_seeker__email")

    def bulk_send_approval_by_email(self, request, queryset):
        queryset = queryset.exclude(approval=None).filter(approval_number_sent_by_email=False)
        for job_application in queryset:
            job_application.send_approval_number_by_email_manually(deliverer=request.user)

    bulk_send_approval_by_email.short_description = _("Envoyer le PASS IAE par email")


@admin.register(models.JobApplicationTransitionLog)
class JobApplicationTransitionLogAdmin(admin.ModelAdmin):
    actions = None
    date_hierarchy = "timestamp"
    list_display = ("job_application", "transition", "from_state", "to_state", "user", "timestamp")
    list_filter = ("transition",)
    raw_id_fields = ("job_application", "user")
    readonly_fields = ("job_application", "transition", "from_state", "to_state", "user", "timestamp")
    search_fields = ("transition", "user__username")
