from django.contrib import admin

from itou.files.models import File
from itou.utils.admin import ItouModelAdmin


@admin.register(File)
class FileAdmin(ItouModelAdmin):
    list_display = ["key", "last_modified"]
    readonly_fields = ["key", "last_modified"]
