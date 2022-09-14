from django.contrib import admin

from .models import FileScanReport


@admin.register(FileScanReport)
class FileScanReportAdmin(admin.ModelAdmin):
    list_display = ["key", "virus", "signature", "reported_at"]
    readonly_fields = ["key", "signature", "reported_at"]
    fields = ["key", "signature", "reported_at", "virus", "comment"]
    list_filter = ["virus"]
    search_fields = ["key", "signature"]
    ordering = ["-reported_at"]

    def has_add_permission(self, request):
        return False
