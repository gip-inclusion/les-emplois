from django.contrib import admin
from django.urls import reverse
from django.utils.safestring import mark_safe
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


class ManualApprovalDeliveryRequiredFilter(admin.SimpleListFilter):
    title = _("Délivrance manuelle de PASS IAE requise")
    parameter_name = "manual_approval_delivery_required"

    def lookups(self, request, model_admin):
        return (("yes", _("Oui")),)

    def queryset(self, request, queryset):
        value = self.value()
        if value == "yes":
            return queryset.manual_approval_delivery_required()
        return queryset


@admin.register(models.JobApplication)
class JobApplicationAdmin(admin.ModelAdmin):
    date_hierarchy = "created_at"
    list_display = ("pk", "state", "sender_kind", "created_at")
    raw_id_fields = ("job_seeker", "sender", "sender_siae", "sender_prescriber_organization", "to_siae", "approval")
    exclude = ("selected_jobs",)
    list_filter = (
        ManualApprovalDeliveryRequiredFilter,
        "sender_kind",
        "state",
        "approval_number_sent_by_email",
        "approval_delivery_mode",
        "sender_prescriber_organization__is_authorized",
        "to_siae__department",
    )
    readonly_fields = ("created_at", "updated_at", "approval_number_delivered_by")
    inlines = (JobsInline, TransitionLogInline)
    search_fields = ("pk", "to_siae__siret", "job_seeker__email", "sender__email")

    def get_form(self, request, obj=None, **kwargs):
        """
        Override a field's `help_text` to display a link to the PASS IAE delivery interface.
        The field is arbitrarily chosen between `approval_*` fields.
        """
        if obj and obj.manual_approval_delivery_required:
            url = reverse("admin:approvals_approval_manually_add_approval", args=[obj.pk])
            text = _("Délivrer un PASS IAE dans l'admin")
            help_texts = {"approval_number_delivered_by": mark_safe(f'<a href="{url}">{text}</a>')}
            kwargs.update({"help_texts": help_texts})
        return super().get_form(request, obj, **kwargs)


@admin.register(models.JobApplicationTransitionLog)
class JobApplicationTransitionLogAdmin(admin.ModelAdmin):
    actions = None
    date_hierarchy = "timestamp"
    list_display = ("job_application", "transition", "from_state", "to_state", "user", "timestamp")
    list_filter = ("transition",)
    raw_id_fields = ("job_application", "user")
    readonly_fields = ("job_application", "transition", "from_state", "to_state", "user", "timestamp")
    search_fields = ("transition", "user__username")
