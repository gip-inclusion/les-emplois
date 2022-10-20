from django.contrib import admin

from itou.external_data import models


@admin.register(models.ExternalDataImport)
class ExternalDataImportAdmin(admin.ModelAdmin):
    raw_id_fields = ("user",)
    list_display = ("pk", "source", "status", "created_at")
    list_filter = ("source", "status")


@admin.register(models.RejectedEmailEventData)
class RejectedEmailEventDataAdmin(admin.ModelAdmin):
    list_filter = ("reason",)
    list_display = ("pk", "recipient", "reason", "created_at")
    search_fields = ("recipient",)
