from django.contrib import admin

from .models import Datum, StatsDashboardVisit


@admin.register(Datum)
class DatumAdmin(admin.ModelAdmin):
    list_display = ["pk", "code", "bucket", "value", "measured_at"]
    list_filter = ["code"]
    ordering = ["-measured_at", "code"]
    date_hierarchy = "measured_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(StatsDashboardVisit)
class StatsDashboardVisitAdmin(admin.ModelAdmin):
    list_display = [
        "measured_at",
        "dashboard_id",
        "department",
        "region",
        "current_siae_id",
        "current_prescriber_organization_id",
        "current_institution_id",
        "user_kind",
    ]
    list_filter = ["dashboard_id", "department", "region", "user_kind"]
    ordering = ["-measured_at"]
    date_hierarchy = "measured_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
