from django.contrib import admin, messages
from django.core.files.storage import default_storage
from django.urls import path, reverse_lazy
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from itou.approvals import models
from itou.approvals.admin_forms import ApprovalAdminForm
from itou.approvals.admin_views import manually_add_approval, manually_refuse_approval, send_approvals_to_pe_stats
from itou.approvals.enums import Origin, ProlongationRequestStatus
from itou.companies.models import Company
from itou.employee_record import enums as employee_record_enums
from itou.employee_record.constants import get_availability_date_for_kind
from itou.employee_record.models import EmployeeRecord
from itou.job_applications.models import JobApplication
from itou.utils.admin import (
    InconsistencyCheckMixin,
    ItouModelAdmin,
    ItouStackedInline,
    ItouTabularInline,
    PkSupportRemarkInline,
    get_admin_view_link,
)


class JobApplicationInline(ItouStackedInline):
    model = JobApplication
    extra = 0
    show_change_link = True
    can_delete = False
    fields = (
        "job_seeker",
        "to_company_link",
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
    list_select_related = ("to_company",)

    # Mandatory for "custom" inline fields
    readonly_fields = ("employee_record_status", "to_company_link")

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description="Entreprises destinataire")
    def to_company_link(self, obj):
        return format_html(
            "{} — SIRET : {} ({})",
            get_admin_view_link(obj.to_company, content=obj.to_company.display_name),
            obj.to_company.siret,
            obj.to_company.kind,
        )

    # Custom read-only fields as workaround :
    # there is no direct relation between approvals and employee records
    # (YET...)
    @staticmethod
    @admin.display(description="situation fiches salariés")
    def employee_record_status(obj):
        if obj.employee_record.exists():
            return mark_safe(
                ", ".join(
                    get_admin_view_link(
                        er,
                        content=mark_safe(f"<b>{er.get_status_display()} (ID: {er.pk})</b>"),
                    )
                    for er in obj.employee_record.all()
                )
            )

        already_exists = None
        if obj.approval:
            already_exists = (
                EmployeeRecord.objects.for_asp_company(obj.to_company)
                .filter(approval_number=obj.approval.number)
                .exists()
            )

        if JobApplication.objects.eligible_as_employee_record(siae=obj.to_company).filter(pk=obj.pk).exists():
            return "En attente de création" + (" (doublon)" if already_exists else "")

        if already_exists:  # Put this check after the eligibility to show that one is proposed but is also a duplicate
            return "Une fiche salarié existe déjà pour ce candidat"

        if not obj.to_company.can_use_employee_record:
            return "La SIAE ne peut pas utiliser la gestion des fiches salarié"

        if not obj.create_employee_record:
            return "Non proposé à la création"

        if obj.hiring_start_at and obj.hiring_start_at < get_availability_date_for_kind(obj.to_company.kind).date():
            return "Date de début du contrat avant l'interopérabilité"

        return "-"


class SuspensionInline(ItouTabularInline):
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


class ProlongationInline(ItouTabularInline):
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


class ProlongationRequestInline(ProlongationInline):
    model = models.ProlongationRequest


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
        return (
            ("past", "< aujourd’hui"),
            ("today", "= aujourd’hui"),
            ("future", "> aujourd’hui"),
        )

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
class ApprovalAdmin(InconsistencyCheckMixin, ItouModelAdmin):
    form = ApprovalAdminForm
    list_display = (
        "pk",
        "number",
        "user",
        "birthdate",
        "start_at",
        "end_at",
        "is_valid",
        "created_at",
    )
    list_select_related = ("user",)
    search_fields = (
        "pk",
        "number",
        "user__first_name__unaccent",
        "user__last_name__unaccent",
        "user__email",
        "user__jobseeker_profile__nir",
    )
    list_filter = (
        IsValidFilter,
        StartDateFilter,
    )
    list_display_links = ("pk", "number")
    raw_id_fields = ("user", "created_by", "eligibility_diagnosis")
    readonly_fields = (
        "created_at",
        "created_by",
        "updated_at",
        "pe_notification_status",
        "pe_notification_time",
        "pe_notification_endpoint",
        "pe_notification_exit_code",
        "assigned_company",
        "origin_prescriber_organization_kind",
        "origin_sender_kind",
        "origin_siae_kind",
        "origin_siae_siret",
    )
    fieldsets = (
        (
            "Informations",
            {
                "fields": (
                    "number",
                    "start_at",
                    "end_at",
                    "user",
                    "eligibility_diagnosis",
                    "assigned_company",
                    "origin",
                    "origin_prescriber_organization_kind",
                    "origin_sender_kind",
                    "origin_siae_kind",
                    "origin_siae_siret",
                )
            },
        ),
        (
            "Audit",
            {
                "fields": (
                    "created_at",
                    "created_by",
                    "updated_at",
                )
            },
        ),
        (
            "Notification à France Travail",
            {
                "fields": (
                    "pe_notification_status",
                    "pe_notification_time",
                    "pe_notification_endpoint",
                    "pe_notification_exit_code",
                )
            },
        ),
    )
    date_hierarchy = "start_at"
    inlines = (
        SuspensionInline,
        ProlongationInline,
        ProlongationRequestInline,
        JobApplicationInline,
        PkSupportRemarkInline,
    )
    change_list_template = "admin/approvals/change_list_with_stats.html"
    stats_url = reverse_lazy("admin:approvals_approval_sent_to_pe_stats")

    INCONSISTENCY_CHECKS = [
        (
            "PASS IAE lié au diagnostic d'un autre candidat",
            lambda q: q.inconsistent_eligibility_diagnosis_job_seeker(),
        ),
    ]

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if company_id := request.GET.get("assigned_company"):
            queryset = queryset.is_assigned_to(company_id)
        return queryset

    def _get_queryset_with_relations(self, request):
        queryset = super()._get_queryset_with_relations(request)
        return queryset.with_assigned_company()

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
            employee_record_links = ", ".join(get_admin_view_link(er) for er in employee_records)
            messages.error(
                request,
                mark_safe(
                    f"Il existe une ou plusieurs fiches salarié bloquantes ({employee_record_links}) "
                    f"pour la modification de ce PASS IAE ({obj.number})."
                ),
            )
            return

        super().save_model(request, obj, form, change)

    @admin.display(boolean=True, description="en cours de validité")
    def is_valid(self, obj):
        return obj.is_valid()

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
            path(
                "sent-to-pe-stats",
                self.admin_site.admin_view(send_approvals_to_pe_stats),
                name="approvals_approval_sent_to_pe_stats",
            ),
        ]
        return additional_urls + super().get_urls()

    @admin.display(description="date de naissance")
    def birthdate(self, obj):
        """
        User birthdate as custom value in display

        """
        return obj.user.birthdate

    @admin.display(description="Entreprise gérant le PASS")
    def assigned_company(self, obj):
        if obj.assigned_company:
            company = Company.objects.get(pk=obj.assigned_company)
            return format_html(
                "{} — SIRET : {}",
                get_admin_view_link(company, content=company.display_name),
                company.siret,
            )
        return "-"


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


class HasReportFile(admin.SimpleListFilter):
    title = "fichier bilan téléversé"
    parameter_name = "report_file"

    def lookups(self, request, model_admin):
        return (("yes", "Oui"), ("no", "Non"))

    def queryset(self, request, queryset):
        value = self.value()
        if value == "yes":
            return queryset.exclude(report_file=None)
        if value == "no":
            return queryset.filter(report_file=None)
        return queryset


class FromProlongationRequest(admin.SimpleListFilter):
    title = "une demande de prolongation"
    parameter_name = "from_prolongation_request"

    def lookups(self, request, model_admin):
        return ("yes", "Oui"), ("no", "Non")

    def queryset(self, request, queryset):
        match self.value():
            case "yes":
                return queryset.filter(request__isnull=False)
            case "no":
                return queryset.filter(request=None)
        return queryset


@admin.register(models.Suspension)
class SuspensionAdmin(ItouModelAdmin):
    list_display = (
        "pk",
        "approval",
        "start_at",
        "end_at",
        "created_at",
        "is_in_progress",
    )
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

    @admin.display(boolean=True, description="en cours")
    def is_in_progress(self, obj):
        return obj.is_in_progress

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


class ProlongationCommonAdmin(ItouModelAdmin):
    list_display = (
        "pk",
        "approval",
        "start_at",
        "end_at",
        "declared_by",
        "validated_by",
        "reason",
    )
    list_display_links = ("pk", "approval")
    raw_id_fields = (
        "approval",
        "declared_by",
        "declared_by_siae",
        "prescriber_organization",
        "validated_by",
        "prescriber_organization",
        "created_by",
        "updated_by",
    )
    exclude = ("report_file",)
    list_filter = ("reason",)
    readonly_fields = (
        "created_at",
        "created_by",
        "updated_at",
        "updated_by",
        "report_file_link",
    )
    inlines = (PkSupportRemarkInline,)
    list_select_related = ("approval", "declared_by", "validated_by")
    search_fields = ["declared_by_siae__siret", "approval__number"]

    def get_list_display(self, request):
        return self.list_display + ("created_at",)  # Put the audit fields after the one added in subclasses

    @admin.display(boolean=True, description="en cours")
    def is_in_progress(self, obj):
        return obj.is_in_progress

    @admin.display(description="lien du fichier bilan")
    def report_file_link(self, obj):
        return format_html(
            "<a href='{}'>{}</a>",
            default_storage.url(obj.report_file.key),
            obj.report_file.key,
        )

    def save_model(self, request, obj, form, change):
        if change:
            obj.updated_by = request.user
        else:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(models.ProlongationRequest)
class ProlongationRequestAdmin(ProlongationCommonAdmin):
    list_display = (
        "pk",
        "approval",
        "created_at",
        "start_at",
        "end_at",
        "declared_by",
        "validated_by",
        "reason",
        "status",
        "processed_at",
    )

    list_filter = ("status", "declared_by_siae__kind", "created_at") + ProlongationCommonAdmin.list_filter

    @admin.display(description="prolongation créée")
    def prolongation(self, obj):
        return obj.prolongation

    @admin.display(description="motif de refus")
    def denied_reason(self, obj):
        return obj.deny_information.reason

    @admin.display(description="explications du motif de refus")
    def denied_reason_explanation(self, obj):
        return obj.deny_information.reason_explanation

    @admin.display(description="actions envisagées")
    def denied_proposed_actions(self, obj):
        if obj.deny_information.proposed_actions is None:
            return "-"
        return "\n".join(obj.deny_information.get_proposed_actions_display())

    @admin.display(description="explications des actions envisagées")
    def denied_proposed_actions_explanation(self, obj):
        return obj.deny_information.proposed_actions_explanation

    def get_readonly_fields(self, request, obj=None):
        fields = ProlongationCommonAdmin.readonly_fields + ("processed_at", "processed_by", "prolongation")
        if not obj:
            return fields

        if obj.status == ProlongationRequestStatus.DENIED:
            fields += (
                "denied_reason",
                "denied_reason_explanation",
                "denied_proposed_actions",
                "denied_proposed_actions_explanation",
            )
        return fields


@admin.register(models.Prolongation)
class ProlongationAdmin(ProlongationCommonAdmin):
    list_display = ProlongationCommonAdmin.list_display + ("is_in_progress", "from_prolongation_request")
    list_select_related = ProlongationCommonAdmin.list_select_related + ("request",)
    raw_id_fields = ProlongationCommonAdmin.raw_id_fields + ("request",)
    list_filter = (
        IsInProgressFilter,
        HasReportFile,
        FromProlongationRequest,
    ) + ProlongationCommonAdmin.list_filter
    date_hierarchy = "start_at"

    @admin.display(boolean=True, description="demande")
    def from_prolongation_request(self, obj):
        return obj.request is not None


@admin.register(models.PoleEmploiApproval)
class PoleEmploiApprovalAdmin(ItouModelAdmin):
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
    search_fields = (
        "pk",
        "pole_emploi_id",
        "nir",
        "number",
        "first_name__unaccent",
        "last_name__unaccent",
        "birth_name",
    )
    list_filter = (IsValidFilter,)
    date_hierarchy = "birthdate"

    @admin.display(boolean=True, description="en cours de validité")
    def is_valid(self, obj):
        return obj.is_valid()


@admin.register(models.CancelledApproval)
class CancelledApprovalAdmin(ItouModelAdmin):
    list_display = (
        "number",
        "start_at",
        "end_at",
        "user_last_name",
        "user_first_name",
        "user_nir",
        "origin_siae_siret",
        "created_at",
    )
    search_fields = (
        "number",
        "user_first_name__unaccent",
        "user_last_name__unaccent",
        "user_nir",
        "origin_siae_siret",
    )
    list_filter = ("origin_siae_kind", "origin_sender_kind", "origin_prescriber_organization_kind")
    change_list_template = "admin/approvals/change_list_with_stats.html"
    stats_url = reverse_lazy("admin:approvals_cancelledapproval_sent_to_pe_stats")

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_urls(self):
        additional_urls = [
            path(
                "sent-to-pe-stats",
                self.admin_site.admin_view(send_approvals_to_pe_stats),
                name="approvals_cancelledapproval_sent_to_pe_stats",
            ),
        ]
        return additional_urls + super().get_urls()
