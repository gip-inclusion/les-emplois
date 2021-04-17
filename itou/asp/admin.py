from django.contrib import admin
from django.utils.translation import gettext as _

from itou.asp import models


class PeriodFilter(admin.SimpleListFilter):
    title = "période de validité"
    parameter_name = "end_date"

    def lookups(self, request, model_admin):
        return (("current", "En cours"), ("old", "Historique"))

    def queryset(self, request, queryset):
        value = self.value()
        if value == "current":
            return queryset.current()
        if value == "old":
            return queryset.old()
        return queryset


class CountryFilter(admin.SimpleListFilter):
    title = "Groupe de pays"
    parameter_name = "group"

    def lookups(self, request, model_admin):
        return models.Country.Group.choices

    def queryset(self, request, queryset):
        value = self.value()
        if value == models.Country.Group.FRANCE:
            return queryset.france()
        elif value == models.Country.Group.CEE:
            return queryset.europe()
        elif value == models.Country.Group.OUTSIDE_CEE:
            return queryset.outside_europe()
        return queryset


class ASPModelAdmin(admin.ModelAdmin):
    list_display = ("pk", "code", "name", "start_date", "end_date")
    list_filter = (PeriodFilter,)
    readonly_fields = ("pk",)
    ordering = ("name",)


@admin.register(models.Commune)
class CommuneAdmin(ASPModelAdmin):
    search_fields = [
        "name",
        "code",
    ]


@admin.register(models.Department)
class DepartmentAdmin(ASPModelAdmin):
    pass


@admin.register(models.Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ("pk", "code", "name")
    readonly_fields = ("pk",)
    ordering = ("name",)
    list_filter = (CountryFilter,)
