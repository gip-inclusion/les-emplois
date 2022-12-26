from django.contrib import admin, messages
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe

import itou.employee_record.models as models

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
            messages.add_message(request, messages.SUCCESS, f"{total_created} notification{s} planifiée{s}")

        total_updated = len(queryset) - total_created
        if total_updated:
            s = pluralizefr(total_updated)
            messages.add_message(request, messages.SUCCESS, f"{total_updated} notification{s} mise{s} à jour")

    actions = [
        update_employee_record_as_ready,
        schedule_approval_update_notification,
    ]

    inlines = (EmployeeRecordUpdateNotificationInline,)

    list_display = (
        "pk",
        "created_at",
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
        "pk",
        "siret",
        "approval_number",
        "asp_processing_code",
        "asp_processing_label",
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
            url = reverse("admin:users_user_change", args=[job_seeker.pk])
            return mark_safe(f'<a href="{url}">{job_seeker}</a>')

        return "-"

    def job_seeker_profile_link(self, obj):
        job_seeker = obj.job_application.job_seeker
        app_label = job_seeker._meta.app_label

        model_name = job_seeker.jobseeker_profile._meta.model_name
        url = reverse(f"admin:{app_label}_{model_name}_change", args=[job_seeker.pk])
        return mark_safe(f'<a href="{url}">Profil salarié ID:{job_seeker.pk}</a>')

    def asp_processing_type(self, obj):
        return (
            "Intégrée automatiquement par script (doublon ASP)"
            if obj.processed_as_duplicate
            else "Intégration ASP normale"
        )

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
        "status",
    )

    list_filter = (
        "status",
        "notification_type",
    )

    raw_id_fields = ("employee_record",)

    readonly_fields = (
        "asp_batch_file",
        "asp_batch_line_number",
        "asp_processing_code",
        "asp_processing_label",
    )

    search_fields = [
        "employee_record__id",
        "employee_record__approval_number",
        "employee_record__asp_id",
        "employee_record__job_application__job_seeker__email",
        "employee_record__job_application__to_siae__siret",
    ]
