from django.contrib import admin

from itou.external_data import models


@admin.register(models.ExternalDataImport)
class ExternalDataImportAdmin(admin.ModelAdmin):
    raw_id_fields = ("user",)
    list_display = ("pk", "source", "status", "created_at")
    list_filter = ("source", "status")


@admin.register(models.JobSeekerExternalData)
class JobSeekerExternalDataAdmin(admin.ModelAdmin):
    raw_id_fields = ("user",)
    list_display = ("pk", "data_import", "created_at")
