from django.contrib import admin

from itou.files.models import File


@admin.register(File)
class FileAdmin(admin.ModelAdmin):
    list_display = ["key", "last_modified"]
    readonly_fields = ["key", "last_modified"]
