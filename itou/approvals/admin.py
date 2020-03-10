from django.contrib import admin
from django.urls import path
from django.utils.translation import gettext_lazy as _

from itou.approvals import models
from itou.approvals.admin_views import manually_add_approval
from itou.job_applications.models import JobApplication


class JobApplicationInline(admin.StackedInline):
    model = JobApplication
    extra = 0
    show_change_link = True
    can_delete = False
    fields = (
        "job_seeker",
        "to_siae",
        "hiring_start_at",
        "hiring_end_at",
        "approval",
        "approval_number_sent_by_email",
        "approval_number_sent_at",
        "approval_delivery_mode",
        "approval_number_delivered_by",
    )
    raw_id_fields = ("job_seeker", "to_siae", "approval_number_delivered_by")

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False


class IsValidFilter(admin.SimpleListFilter):
    title = _("En cours de validité")
    parameter_name = "is_valid"

    def lookups(self, request, model_admin):
        return (("yes", _("Oui")), ("no", _("Non")))

    def queryset(self, request, queryset):
        value = self.value()
        if value == "yes":
            return queryset.valid()
        if value == "no":
            return queryset.invalid()
        return queryset


@admin.register(models.Approval)
class ApprovalAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "number",
        "user",
        "start_at",
        "end_at",
        "is_valid",
        "created_at",
    )
    search_fields = ("number", "user__first_name", "user__last_name", "user__email")
    list_filter = (IsValidFilter,)
    list_display_links = ("id", "number")
    raw_id_fields = ("user", "created_by")
    readonly_fields = ("created_at", "created_by")
    date_hierarchy = "start_at"
    inlines = (JobApplicationInline,)

    def save_model(self, request, obj, form, change):
        if not obj.pk:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def is_valid(self, obj):
        return obj.is_valid

    is_valid.boolean = True
    is_valid.short_description = _("En cours de validité")

    def manually_add_approval(self, request, job_application_id):
        """
        Custom admin view to manually add an approval.
        """
        return manually_add_approval(request, self, job_application_id)

    def get_urls(self):
        additional_urls = [
            path(
                "<uuid:job_application_id>/add_approval",
                self.admin_site.admin_view(self.manually_add_approval),
                name="approvals_approval_manually_add_approval",
            )
        ]
        return additional_urls + super().get_urls()


@admin.register(models.PoleEmploiApproval)
class PoleEmploiApprovalAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "pole_emploi_id",
        "number",
        "first_name",
        "last_name",
        "birth_name",
        "start_at",
        "end_at",
        "is_valid",
    )
    search_fields = (
        "pole_emploi_id",
        "number",
        "first_name",
        "last_name",
        "birth_name",
    )
    list_filter = (IsValidFilter,)
    date_hierarchy = "start_at"

    def is_valid(self, obj):
        return obj.is_valid

    is_valid.boolean = True
    is_valid.short_description = _("En cours de validité")
