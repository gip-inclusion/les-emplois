from django.contrib import admin
from django.contrib.admin.models import LogEntry
from django.contrib.contenttypes.admin import GenericStackedInline
from django_admin_logs.admin import LogEntryAdmin

from itou.utils.models import SupportRemark


class SupportRemarkInline(GenericStackedInline):
    model = SupportRemark
    min_num = 0
    max_num = 1
    extra = 1
    can_delete = False


# Hides the LogEntry section in the admin interface
class LogEntryAdminHidden(LogEntryAdmin):
    def has_view_permission(self, request, obj=None):
        return False


admin.site.unregister(LogEntry)
admin.site.register(LogEntry, LogEntryAdminHidden)
