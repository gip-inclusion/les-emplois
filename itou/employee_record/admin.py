from django.contrib import admin

import itou.employee_record.models as models
from itou.job_applications.models import JobApplication


class JobSeekerInline(admin.StackedInline):
    model = JobApplication
    readonly_fields = ("pk",)
    fields = (
        "title",
        "birth_country",
        "birth_place",
    )

    def title(self, obj):
        return obj.job_seeker.title

    def birth_country(self, obj):
        return obj.job_seeker.birth_country

    def birth_place(self, obj):
        return obj.job_seeker.birth_place


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
        "created_at",
        "updated_at",
        "asp_processing_code",
        "asp_process_response",
        "archived_json",
    )

    # inlines = (JobSeekerInline, )
