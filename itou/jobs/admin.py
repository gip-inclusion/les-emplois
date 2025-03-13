from django.contrib import admin

from itou.jobs import models
from itou.utils.admin import ItouModelAdmin, ItouTabularInline, ReadonlyMixin


class AppellationsInline(ItouTabularInline, ReadonlyMixin):
    model = models.Appellation
    readonly_fields = ("code", "name")


@admin.register(models.Rome)
class RomeAdmin(ItouModelAdmin, ReadonlyMixin):
    list_display = ("code", "name")
    search_fields = ("code", "name")
    inlines = (AppellationsInline,)


@admin.register(models.Appellation)
class AppellationAdmin(ItouModelAdmin, ReadonlyMixin):
    list_display = ("code", "name")
    search_fields = ("code", "name", "rome__code")
    raw_id_fields = ("rome",)
