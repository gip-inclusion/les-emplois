import datetime

from django.contrib import admin
from django.http import HttpResponse
from django.urls import path
from django.utils.translation import gettext_lazy as _

from itou.approvals import models
from itou.approvals.admin_views import manually_add_approval
from itou.approvals.export import export_approvals
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

    def has_add_permission(self, request, obj=None):
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
    list_display = ("pk", "number", "user", "start_at", "end_at", "is_valid", "created_at")
    search_fields = ("pk", "number", "user__first_name", "user__last_name", "user__email")
    list_filter = (IsValidFilter,)
    list_display_links = ("pk", "number")
    raw_id_fields = ("user", "created_by")
    readonly_fields = ("created_at", "created_by")
    date_hierarchy = "start_at"
    inlines = (JobApplicationInline,)
    actions = ["export_approvals"]

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

    def export_approvals(self, request):
        """
        Custom admin view to export all approvals as an XLSX file.
        """
        filename, file_content = export_approvals(export_format="stream")
        response = HttpResponse(content=file_content, content_type="application/ms-excel")
        response["Content-Disposition"] = f"attachment; filename={filename}"
        return response

    def get_urls(self):
        additional_urls = [
            path(
                "<uuid:job_application_id>/add_approval",
                self.admin_site.admin_view(self.manually_add_approval),
                name="approvals_approval_manually_add_approval",
            ),
            path(
                "export_approvals",
                self.admin_site.admin_view(self.export_approvals),
                name="approvals_approval_export_approvals",
            ),
        ]
        return additional_urls + super().get_urls()


class ImportDateFilter(admin.SimpleListFilter):
    """
    Allow to filter results by import date.
    """

    DATE_FORMAT = "%d-%m-%Y"
    title = _("Date de l'import")
    parameter_name = "import_date"

    def lookups(self, request, model_admin):
        return [
            (import_date.strftime(self.DATE_FORMAT), import_date.strftime(self.DATE_FORMAT))
            for import_date in models.PoleEmploiApproval.objects.get_import_dates()
        ]

    def queryset(self, request, queryset):
        value = self.value()
        if value:
            try:
                import_date = datetime.datetime.strptime(value, self.DATE_FORMAT).date()
                return queryset.filter(created_at__date=import_date)
            except ValueError:
                pass
        return queryset


@admin.register(models.PoleEmploiApproval)
class PoleEmploiApprovalAdmin(admin.ModelAdmin):
    list_display = (
        "pk",
        "pole_emploi_id",
        "number",
        "first_name",
        "last_name",
        "birth_name",
        "birthdate",
        "start_at",
        "end_at",
        "is_valid",
        "created_at",
    )
    search_fields = ("pk", "pole_emploi_id", "number", "first_name", "last_name", "birth_name")
    list_filter = (IsValidFilter, ImportDateFilter)
    date_hierarchy = "birthdate"

    def is_valid(self, obj):
        return obj.is_valid

    is_valid.boolean = True
    is_valid.short_description = _("En cours de validité")
