from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin

from ..utils.admin import ItouModelAdmin
from .models import QPV, ZRR


@admin.register(QPV)
class QPVAdmin(GISModelAdmin):
    list_display = (
        "pk",
        "code",
        "name",
    )

    search_fields = ("code",)
    ordering = ("code",)

    fields = (
        "code",
        "name",
        "communes_info",
    )

    # GIS reference models are read-only
    # TODO: find a way to display map of a geometry in "read-only" mode
    actions = None

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ZRR)
class ZRRAdmin(ItouModelAdmin):
    list_display = ("pk", "insee_code", "status")
    list_filter = ("status",)

    ordering = ("insee_code",)

    fields = (
        "insee_code",
        "status",
    )
    actions = None

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
