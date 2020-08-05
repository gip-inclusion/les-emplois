from django.contrib import admin

from itou.external_data import models


@admin.register(models.ExternalDataImport)
class ExternalDataImportAdmin(admin.ModelAdmin):
    list_display = ("pk", "source", "status", "user", "created_at")
    list_filter = ("source", "status")


@admin.register(models.JobSeekerExternalData)
class JobSeekerExternalDataAdmin(admin.ModelAdmin):
    list_display = ("pk", "data_import", "user", "created_at")
