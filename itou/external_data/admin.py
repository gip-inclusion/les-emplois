from django.contrib import admin

from itou.external_data import models
from itou.utils.admin import ItouModelAdmin


@admin.register(models.ExternalDataImport)
class ExternalDataImportAdmin(ItouModelAdmin):
    raw_id_fields = ("user",)
    list_display = ("pk", "source", "status", "created_at")
    list_filter = ("source", "status")
