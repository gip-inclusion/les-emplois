from django.contrib import admin

from itou.jobs import models
from itou.utils.admin import ItouModelAdmin, ItouTabularInline


class AppellationsInline(ItouTabularInline):
    model = models.Appellation
    readonly_fields = ("code", "name")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(models.Rome)
class RomeAdmin(ItouModelAdmin):
    list_display = ("code", "name")
    search_fields = ("code", "name")
    inlines = (AppellationsInline,)


@admin.register(models.Appellation)
class AppellationAdmin(ItouModelAdmin):
    list_display = ("code", "name")
    search_fields = ("code", "name", "rome__code")
    raw_id_fields = ("rome",)
