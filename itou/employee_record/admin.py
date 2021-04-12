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

    raw_id_fields = (
        "job_application",
        "financial_annex",
    )

    readonly_fields = (
        "title",
        "birth_country",
        "birth_place",
        "created_at",
        "updated_at",
        "asp_processing_code",
        "asp_process_response",
        "archived_json",
    )

    def title(self, obj):
        return obj.job_application.job_seeker.title

    def birth_country(self, obj):
        return obj.job_application.job_seeker.birth_country

    def birth_place(self, obj):
        return obj.job_application.job_seeker.birth_place
