from django.contrib import admin

from itou.jobs import models
from itou.utils.admin import ItouModelAdmin, ItouTabularInline, ReadonlyMixin


class AppellationsInline(ReadonlyMixin, ItouTabularInline):
    model = models.Appellation
    readonly_fields = ("code", "name")


@admin.register(models.Rome)
class RomeAdmin(ReadonlyMixin, ItouModelAdmin):
    list_display = ("code", "name")
    search_fields = ("code", "name")
    inlines = (AppellationsInline,)


@admin.register(models.Appellation)
class AppellationAdmin(ReadonlyMixin, ItouModelAdmin):
    list_display = ("code", "name")
    search_fields = ("code", "name", "rome__code")
    raw_id_fields = ("rome",)
