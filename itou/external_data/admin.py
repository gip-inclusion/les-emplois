from django.contrib import admin

from itou.external_data import models


@admin.register(models.ExternalDataImport)
class ExternalDataImportAdmin(admin.ModelAdmin):
    list_display = ("id", "source", "status", "user", "created_at")
    list_filter = ("source", "status")


@admin.register(models.ExternalUserData)
class ExternalUserDataAdmin(admin.ModelAdmin):
    list_display = ("id", "key", "value", "created_at")
