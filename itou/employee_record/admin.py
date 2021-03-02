from django.contrib import admin

import itou.employee_record.models as models


@admin.register(models.EmployeeRecord)
class EmployeeRecordAdmin(admin.ModelAdmin):
    list_display = (
        "pk",
        "__str__",
        "created_at",
        "status",
    )
    list_filter = ("status",)

    raw_id_fields = ("job_application",)
    readonly_fields = (
        "siret",
        "created_at",
        "updated_at",
        "asp_processing_code",
        "asp_process_response",
        "archived_json",
    )
