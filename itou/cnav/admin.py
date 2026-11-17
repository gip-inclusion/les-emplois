from django.contrib import admin

from itou.cnav.models import CNAVRecord
from itou.utils.admin import ItouModelAdmin, ReadonlyMixin


@admin.register(CNAVRecord)
class CNAVRecordAdmin(ReadonlyMixin, ItouModelAdmin):
    list_display = ["created_at", "profile", "has_result"]

    @admin.display(description="Traité", boolean=True)
    def has_result(self, obj):
        return obj.result is not None
