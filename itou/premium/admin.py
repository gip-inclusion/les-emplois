from django.contrib import admin

from itou.premium.models import Note


@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = ("job_application", "created_by")
    raw_id_fields = ("job_application", "created_by", "updated_by")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
