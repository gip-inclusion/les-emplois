from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin
from django.core.exceptions import PermissionDenied

from itou.geo.models import QPV, ZRR
from itou.utils.admin import ItouGISMixin, ItouModelAdmin, ItouModelMixin


@admin.register(QPV)
class QPVAdmin(ItouModelMixin, ItouGISMixin, GISModelAdmin):
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
        "geometry",
    )
    readonly_fields = ("code", "name", "communes_info")

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        # Return True to make Django believe that edition is allowed and actually display a proper map widget.
        # But we don`t want users to be able to change QPV objects: change_view is overridden to prevent it.
        # Cf https://forum.djangoproject.com/t/geodjango-read-only-fields-visible-on-map-in-admin-panel/38199/3
        # or https://code.djangoproject.com/ticket/30577
        return True

    def has_delete_permission(self, request, obj=None):
        return False

    def change_view(self, request, object_id, form_url="", extra_context=None):
        if request.method not in ("GET", "HEAD", "OPTIONS", "TRACE"):
            raise PermissionDenied
        if extra_context is None:
            extra_context = {}
        # Hide save buttons to prevent users from trying to save changes
        extra_context["show_save"] = False
        extra_context["show_save_and_continue"] = False
        return super().change_view(request, object_id, form_url=form_url, extra_context=extra_context)


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
