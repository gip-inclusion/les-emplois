from django.contrib import admin
from django.utils.translation import gettext as _

from itou.asp import models


class PeriodFilter(admin.SimpleListFilter):
    title = _("période de validité")
    parameter_name = "end_date"

    def lookups(self, request, model_admin):
        return (("current", _("En cours")), ("old", _("Historique")))

    def queryset(self, request, queryset):
        value = self.value()
        if value == "current":
            return queryset.current()
        if value == "old":
            return queryset.old()
        return queryset


class ASPModelAdmin(admin.ModelAdmin):
    list_display = ("pk", "code", "name", "start_date", "end_date")
    list_filter = (PeriodFilter,)
    readonly_fields = ("pk",)
    ordering = ("name",)


@admin.register(models.Commune)
class CommuneAdmin(ASPModelAdmin):
    pass


@admin.register(models.EducationLevel)
class EducationLevelAdmin(ASPModelAdmin):
    pass


@admin.register(models.Department)
class DepartmentAdmin(ASPModelAdmin):
    pass


@admin.register(models.Measure)
class MeasureAdmin(ASPModelAdmin):
    pass


@admin.register(models.EmployerType)
class EmployerTypeAdmin(ASPModelAdmin):
    pass


@admin.register(models.Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ("pk", "code", "name")
    readonly_fields = ("pk",)
    ordering = ("name",)
