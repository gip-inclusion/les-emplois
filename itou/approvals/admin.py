from django.contrib import admin, messages
from django.urls import path
from django.urls.base import reverse
from django.utils.html import format_html

from itou.approvals import models
from itou.approvals.admin_forms import ApprovalAdminForm
from itou.approvals.admin_views import manually_add_approval, manually_refuse_approval
from itou.employee_record.models import EmployeeRecord
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
        "approval_manually_delivered_by",
        "employee_record_status",
    )
    raw_id_fields = (
        "job_seeker",
        "to_siae",
        "approval_manually_delivered_by",
    )

    # Mandatory for "custom" inline fields
    readonly_fields = ("employee_record_status",)

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request, obj=None):
        return False

    # Custom read-only fields as workaround :
    # there is no direct relation between approvals and employee records
    # (YET...)
    @admin.display(description="Statut de la fiche salarié")
    def employee_record_status(self, obj):
        if employee_record := obj.employee_record.first():
            url = reverse("admin:employee_record_employeerecord_change", args=[employee_record.id])
            display = employee_record.get_status_display()
            return format_html(f"<a href='{url}'><b>{display} (ID : {employee_record.id})</b></a>")

        return "Pas de fiche salarié crée pour cette candidature"


class SuspensionInline(admin.TabularInline):
    model = models.Suspension
    extra = 0
    show_change_link = True
    can_delete = False
    fields = ("start_at", "end_at", "reason", "created_by", "siae")
    raw_id_fields = ("approval", "siae", "created_by", "updated_by")

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request, obj=None):
        return False


class ProlongationInline(admin.TabularInline):
    model = models.Prolongation
    extra = 0
    show_change_link = True
    can_delete = False
    fields = ("start_at", "end_at", "reason", "declared_by", "validated_by")
    raw_id_fields = ("declared_by", "validated_by")

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request, obj=None):
        return False


class IsValidFilter(admin.SimpleListFilter):
    title = "En cours de validité"
    parameter_name = "is_valid"

    def lookups(self, request, model_admin):
        return (("yes", "Oui"), ("no", "Non"))

    def queryset(self, request, queryset):
        value = self.value()
        if value == "yes":
            return queryset.valid()
        if value == "no":
            return queryset.invalid()
        return queryset


@admin.register(models.Approval)
class ApprovalAdmin(admin.ModelAdmin):
    form = ApprovalAdminForm
    list_display = ("pk", "number", "user", "start_at", "end_at", "is_valid", "created_at")
    search_fields = ("pk", "number", "user__first_name", "user__last_name", "user__email")
    list_filter = (IsValidFilter,)
    list_display_links = ("pk", "number")
    raw_id_fields = ("user", "created_by")
    readonly_fields = ("created_at", "created_by")
    date_hierarchy = "start_at"
    inlines = (
        SuspensionInline,
        ProlongationInline,
        JobApplicationInline,
    )

    def save_model(self, request, obj, form, change):
        if not obj.pk:
            obj.created_by = request.user

        # Is there an employee record linked ?
        employee_record = EmployeeRecord.objects.filter(approval_number=obj.number).first()
        if employee_record and employee_record.status in [EmployeeRecord.Status.PROCESSED, EmployeeRecord.Status.SENT]:
            messages.set_level(request, messages.ERROR)
            messages.error(
                request,
                f"Il existe une fiche salarié bloquante (ID: {employee_record.pk})"
                "pour la modification de ce PASS IAE ({obj.number}).",
            )
            return

        super().save_model(request, obj, form, change)

    def is_valid(self, obj):
        return obj.is_valid()

    is_valid.boolean = True
    is_valid.short_description = "En cours de validité"

    def manually_add_approval(self, request, job_application_id):
        """
        Custom admin view to manually add an approval.
        """
        return manually_add_approval(request, self, job_application_id)

    def manually_refuse_approval(self, request, job_application_id):
        """
        Custom admin view to manually refuse an approval.
        """
        return manually_refuse_approval(request, self, job_application_id)

    def get_urls(self):
        additional_urls = [
            path(
                "<uuid:job_application_id>/add_approval",
                self.admin_site.admin_view(self.manually_add_approval),
                name="approvals_approval_manually_add_approval",
            ),
            path(
                "<uuid:job_application_id>/refuse_approval",
                self.admin_site.admin_view(self.manually_refuse_approval),
                name="approvals_approval_manually_refuse_approval",
            ),
        ]
        return additional_urls + super().get_urls()


class IsInProgressFilter(admin.SimpleListFilter):
    title = "En cours"
    parameter_name = "is_progress"

    def lookups(self, request, model_admin):
        return (("yes", "Oui"), ("no", "Non"))

    def queryset(self, request, queryset):
        value = self.value()
        if value == "yes":
            return queryset.in_progress()
        if value == "no":
            return queryset.not_in_progress()
        return queryset


@admin.register(models.Suspension)
class SuspensionAdmin(admin.ModelAdmin):
    list_display = ("pk", "approval", "start_at", "end_at", "created_at", "is_in_progress")
    list_display_links = ("pk", "approval")
    raw_id_fields = ("approval", "siae", "created_by", "updated_by")
    list_filter = (
        IsInProgressFilter,
        "reason",
    )
    readonly_fields = ("created_at", "created_by", "updated_at", "updated_by")
    date_hierarchy = "start_at"

    def is_in_progress(self, obj):
        return obj.is_in_progress

    is_in_progress.boolean = True
    is_in_progress.short_description = "En cours"

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(models.Prolongation)
class ProlongationAdmin(admin.ModelAdmin):
    list_display = (
        "pk",
        "approval",
        "start_at",
        "end_at",
        "declared_by",
        "validated_by",
        "created_at",
        "is_in_progress",
    )
    list_display_links = ("pk", "approval")
    raw_id_fields = (
        "approval",
        "declared_by",
        "declared_by_siae",
        "validated_by",
        "created_by",
        "updated_by",
    )
    list_filter = (
        IsInProgressFilter,
        "reason",
    )
    date_hierarchy = "start_at"
    readonly_fields = (
        "created_at",
        "created_by",
        "updated_at",
        "updated_by",
    )

    def is_in_progress(self, obj):
        return obj.is_in_progress

    is_in_progress.boolean = True
    is_in_progress.short_description = "En cours"

    def get_queryset(self, request):
        # Speed up the list display view by fecthing related objects.
        return super().get_queryset(request).select_related("approval", "declared_by", "validated_by")

    def save_model(self, request, obj, form, change):
        if change:
            obj.updated_by = request.user
        else:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


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
    list_filter = (IsValidFilter,)
    date_hierarchy = "birthdate"

    def is_valid(self, obj):
        return obj.is_valid()

    is_valid.boolean = True
    is_valid.short_description = "En cours de validité"
