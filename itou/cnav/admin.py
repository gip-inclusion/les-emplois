from django.contrib import admin

from itou.cnav.models import CNAVRecord
from itou.utils.admin import ItouModelAdmin, ReadonlyMixin


@admin.register(CNAVRecord)
class CNAVRecordAdmin(ReadonlyMixin, ItouModelAdmin):
    list_display = ["created_at", "profile", "has_result_code"]

    @admin.display(description="Traité", boolean=True)
    def has_result_code(self, obj):
        return bool(obj.result_code)
