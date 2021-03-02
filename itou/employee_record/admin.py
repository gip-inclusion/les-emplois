from django.contrib import admin

import itou.employee_record.models as models


@admin.register(models.EmployeeRecord)
class EmployeeRecordAdmin(admin.ModelAdmin):
    raw_id_fields = ("job_application",)
    readonly_fields = (
        "created_at",
        "updated_at",
        "asp_processing_code",
        "asp_process_response",
        "archived_json",
    )
