from django.contrib import admin, messages
from django.utils import timezone

import itou.employee_record.models as models

from ..utils.admin import get_admin_view_link
from ..utils.templatetags.str_filters import pluralizefr
from .enums import Status


class EmployeeRecordUpdateNotificationInline(admin.TabularInline):
    model = models.EmployeeRecordUpdateNotification

    fields = (
        "created_at",
        "status",
        "asp_batch_file",
        "asp_batch_line_number",
    )

    readonly_fields = fields
    fk_name = "employee_record"

    can_delete = False
    show_change_link = True
    extra = 0


@admin.register(models.EmployeeRecord)
class EmployeeRecordAdmin(admin.ModelAdmin):
    @admin.action(description="Marquer les fiches salarié selectionnées comme COMPLETÉES")
    def update_employee_record_as_ready(self, _request, queryset):
        queryset.update(status=Status.READY)

    @admin.action(description="Planifier une notification de changement 'PASS IAE' pour ces fiches salarié")
    def schedule_approval_update_notification(self, request, queryset):
        total_created = 0
        for employee_record in queryset:
            _, created = models.EmployeeRecordUpdateNotification.objects.update_or_create(
                employee_record=employee_record,
                notification_type=models.NotificationType.APPROVAL,
                status=Status.NEW,
                defaults={"updated_at": timezone.now},
            )
            total_created += int(created)

        if total_created:
            s = pluralizefr(total_created)
            messages.success(request, f"{total_created} notification{s} planifiée{s}")

        total_updated = len(queryset) - total_created
        if total_updated:
            s = pluralizefr(total_updated)
            messages.success(request, f"{total_updated} notification{s} mise{s} à jour")

    actions = [
        update_employee_record_as_ready,
        schedule_approval_update_notification,
    ]

    inlines = (EmployeeRecordUpdateNotificationInline,)

    list_display = (
        "pk",
        "created_at",
        "updated_at",
        "approval_number",
        "siret",
        "asp_processing_code",
        "status",
    )

    list_filter = (
        "status",
        "processed_as_duplicate",
    )

    search_fields = (
        "siret",
        "approval_number",
        "asp_batch_file",
    )

    raw_id_fields = (
        "job_application",
        "financial_annex",
    )

    readonly_fields = (
        "pk",
        "created_at",
        "updated_at",
        "approval_number",
        "job_application",
        "job_seeker_link",
        "job_seeker_profile_link",
        "siret",
        "financial_annex",
        "asp_id",
        "asp_processing_type",
        "asp_batch_file",
        "asp_batch_line_number",
        "asp_processing_code",
        "asp_processing_label",
        "archived_json",
    )

    fieldsets = (
        (
            "Informations",
            {
                "fields": (
                    "pk",
                    "status",
                    "job_application",
                    "approval_number",
                    "job_seeker_link",
                    "job_seeker_profile_link",
                    "siret",
                    "asp_id",
                    "financial_annex",
                    "created_at",
                    "updated_at",
                )
            },
        ),
        (
            "Traitement ASP",
            {
                "fields": (
                    "asp_batch_file",
                    "asp_batch_line_number",
                    "asp_processing_code",
                    "asp_processing_label",
                    "asp_processing_type",
                    "archived_json",
                )
            },
        ),
    )

    def job_seeker_link(self, obj):
        if job_seeker := obj.job_application.job_seeker:
            return get_admin_view_link(job_seeker, content=job_seeker)

        return "-"

    def job_seeker_profile_link(self, obj):
        job_seeker_profile = obj.job_application.job_seeker.jobseeker_profile
        return get_admin_view_link(job_seeker_profile, content=f"Profil salarié ID:{job_seeker_profile.pk}")

    def asp_processing_type(self, obj):
        if obj.processed_as_duplicate:
            return "Intégrée automatiquement par script (doublon ASP)"
        if obj.asp_processing_code:
            return "Intégration ASP normale"
        return "-"

    asp_processing_type.short_description = "Type d'intégration"
    job_seeker_link.short_description = "Salarié"
    job_seeker_profile_link.short_description = "Profil du salarié"


@admin.register(models.EmployeeRecordUpdateNotification)
class EmployeeRecordUpdateNotificationAdmin(admin.ModelAdmin):
    list_display = (
        "pk",
        "created_at",
        "updated_at",
        "notification_type",
        "asp_processing_code",
        "status",
    )

    list_filter = (
        "status",
        "notification_type",
    )

    raw_id_fields = ("employee_record",)

    readonly_fields = (
        "pk",
        "employee_record",
        "created_at",
        "updated_at",
        "asp_batch_file",
        "asp_batch_line_number",
        "asp_processing_code",
        "asp_processing_label",
        "archived_json",
    )

    search_fields = [
        "employee_record__siret",
        "employee_record__approval_number",
        "asp_batch_file",
    ]

    fieldsets = (
        (
            "Informations",
            {
                "fields": (
                    "pk",
                    "status",
                    "employee_record",
                    "created_at",
                    "updated_at",
                )
            },
        ),
        (
            "Traitement ASP",
            {
                "fields": (
                    "asp_batch_file",
                    "asp_batch_line_number",
                    "asp_processing_code",
                    "asp_processing_label",
                    "archived_json",
                )
            },
        ),
    )
