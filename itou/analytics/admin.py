from django.contrib import admin

from itou.analytics.models import Datum, StatsDashboardVisit
from itou.utils.admin import ItouModelAdmin


@admin.register(Datum)
class DatumAdmin(ItouModelAdmin):
    list_display = ["pk", "code", "bucket", "get_value_display", "measured_at"]
    list_filter = ["code"]
    fields = ["code", "bucket", "get_value_display", "measured_at"]
    ordering = ["-measured_at", "code"]
    date_hierarchy = "measured_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="value")
    def get_value_display(self, obj):
        return obj.get_value_display()


@admin.register(StatsDashboardVisit)
class StatsDashboardVisitAdmin(ItouModelAdmin):
    list_display = [
        "measured_at",
        "dashboard_id",
        "dashboard_name",
        "department",
        "region",
        "current_company_id",
        "current_prescriber_organization_id",
        "current_institution_id",
        "user_kind",
    ]
    list_filter = ["dashboard_name", "department", "region", "user_kind"]
    ordering = ["-measured_at"]
    date_hierarchy = "measured_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
