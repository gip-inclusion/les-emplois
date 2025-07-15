from django.contrib import admin
from django.utils.html import format_html

from itou.files.models import File
from itou.utils.admin import ItouModelAdmin


@admin.register(File)
class FileAdmin(ItouModelAdmin):
    list_display = ["key", "last_modified"]
    readonly_fields = ["key", "link", "last_modified"]

    fields = ["key", "link", "last_modified"]

    @admin.display(description="lien")
    def link(self, obj):
        return format_html(
            "<a href='{}' target='_blank'>Télécharger</a>",
            obj.url(),
        )
