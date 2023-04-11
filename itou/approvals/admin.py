from django.contrib import admin, messages
from django.urls import path
from django.urls.base import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from itou.approvals import models
from itou.approvals.admin_forms import ApprovalAdminForm
from itou.approvals.admin_views import manually_add_approval, manually_refuse_approval
from itou.approvals.enums import Origin
from itou.employee_record import enums as employee_record_enums
from itou.employee_record.constants import EMPLOYEE_RECORD_FEATURE_AVAILABILITY_DATE
from itou.employee_record.models import EmployeeRecord
from itou.job_applications.models import JobApplication
from itou.utils.admin import PkSupportRemarkInline


class JobApplicationInline(admin.StackedInline):
    model = JobApplication
    extra = 0
    show_change_link = True
    can_delete = False
    fields = (
        "job_seeker",
        "to_siae_link",
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
        "approval_manually_delivered_by",
    )

    # Mandatory for "custom" inline fields
    readonly_fields = ("employee_record_status", "to_siae_link")

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description="SIAE destinataire")
    def to_siae_link(self, obj):
        to_siae_link = reverse("admin:siaes_siae_change", args=[obj.to_siae.pk])
        return format_html(f"<a href='{to_siae_link}'>{obj.to_siae.display_name}</a> — SIRET : {obj.to_siae.siret}")

    # Custom read-only fields as workaround :
    # there is no direct relation between approvals and employee records
    # (YET...)
    @staticmethod
    @admin.display(description="Statut de la fiche salarié")
    def employee_record_status(obj):
        if employee_record := obj.employee_record.first():
            url = reverse("admin:employee_record_employeerecord_change", args=[employee_record.id])
            debug = f"ID: {employee_record.id}"
            if employee_record.is_orphan:
                debug += ", ORPHAN"
            return format_html(f"<a href='{url}'><b>{employee_record.get_status_display()} ({debug})</b></a>")

        if not obj.to_siae.can_use_employee_record:
            return "La SIAE n'utilise pas les fiches salariés"

        if not obj.create_employee_record:
            return "Création désactivée"

        if obj.hiring_start_at and obj.hiring_start_at < EMPLOYEE_RECORD_FEATURE_AVAILABILITY_DATE.date():
            return "Date de début du contrat avant l'interopérabilité"

        already_exists = obj.candidate_has_employee_record

        if JobApplication.objects.eligible_as_employee_record(siae=obj.to_siae).filter(pk=obj.pk).exists():
            return "En attente de création" + (" (doublon)" if already_exists else "")

        if already_exists:  # Put this check after the eligibility to show that one is proposed but is also a duplicate
            return "Une fiche salarié existe déjà pour ce candidat"

        return "-"


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


class StartDateFilter(admin.SimpleListFilter):
    title = "Date de début"
    parameter_name = "starts"

    def lookups(self, request, model_admin):
        return (("past", "< aujourd’hui"), ("today", "= aujourd’hui"), ("future", "> aujourd’hui"))

    def queryset(self, request, queryset):
        value = self.value()
        if value == "past":
            return queryset.starts_in_the_past()
        if value == "today":
            return queryset.starts_today()
        if value == "future":
            return queryset.starts_in_the_future()
        return queryset


@admin.register(models.Approval)
class ApprovalAdmin(admin.ModelAdmin):
    form = ApprovalAdminForm
    list_display = ("pk", "number", "user", "birthdate", "start_at", "end_at", "is_valid", "created_at")
    list_select_related = ("user",)
    search_fields = ("pk", "number", "user__first_name", "user__last_name", "user__email")
    list_filter = (
        IsValidFilter,
        StartDateFilter,
    )
    list_display_links = ("pk", "number")
    raw_id_fields = ("user", "created_by", "eligibility_diagnosis")
    readonly_fields = (
        "created_at",
        "created_by",
        "pe_notification_status",
        "pe_notification_time",
        "pe_notification_endpoint",
        "pe_notification_exit_code",
    )
    date_hierarchy = "start_at"
    inlines = (
        SuspensionInline,
        ProlongationInline,
        JobApplicationInline,
        PkSupportRemarkInline,
    )

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return ("origin",) + self.readonly_fields
        return self.readonly_fields

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
            obj.origin = Origin.ADMIN

        # Prevent the approval modification when an employee record exists and is READY, SENT, or PROCESSED
        employee_records = EmployeeRecord.objects.filter(
            approval_number=obj.number,
            status__in=[
                employee_record_enums.Status.READY,
                employee_record_enums.Status.SENT,
                employee_record_enums.Status.PROCESSED,
            ],
        )
        if employee_records:
            employee_record_links = ", ".join(
                '<a href="'
                + reverse(f"admin:{er._meta.app_label}_{er._meta.model_name}_change", args=[er.pk])
                + f'">{er.pk}</a>'
                for er in employee_records
            )
            messages.set_level(request, messages.ERROR)
            messages.error(
                request,
                mark_safe(
                    f"Il existe une ou plusieurs fiches salarié bloquantes ({employee_record_links}) "
                    f"pour la modification de ce PASS IAE ({obj.number})."
                ),
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

    def birthdate(self, obj):
        """
        User birthdate as custom value in display

        """
        return obj.user.birthdate

    birthdate.short_description = "Date de naissance"


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
    search_fields = (
        "pk",
        "approval__number",
    )
    inlines = (PkSupportRemarkInline,)

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
    inlines = (PkSupportRemarkInline,)

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
    search_fields = ("pk", "pole_emploi_id", "nir", "number", "first_name", "last_name", "birth_name")
    list_filter = (IsValidFilter,)
    date_hierarchy = "birthdate"

    def is_valid(self, obj):
        return obj.is_valid()

    is_valid.boolean = True
    is_valid.short_description = "En cours de validité"
