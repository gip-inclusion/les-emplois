from django.contrib import admin

import itou.employee_record.models as models


@admin.register(models.EmployeeRecord)
class EmployeeRecordAdmin(admin.ModelAdmin):
    list_display = (
        "pk",
        "created_at",
        "approval_number",
        "siret",
        "asp_processing_code",
        "status",
    )
    list_filter = ("status",)

    search_fields = (
        "pk",
        "siret",
        "approval_number",
        "asp_processing_code",
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
        "siret",
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
                    "archived_json",
                )
            },
        ),
    )
