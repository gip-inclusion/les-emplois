from django.contrib import admin, messages

from itou.asp import models
from itou.utils.admin import ItouModelAdmin, PkSupportRemarkInline


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


class ASPModelAdmin(ItouModelAdmin):
    list_display = ("pk", "code", "name", "start_date", "end_date")
    list_filter = (PeriodFilter,)
    readonly_fields = ("pk",)
    ordering = ("name",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(models.Commune)
class CommuneAdmin(ASPModelAdmin):
    list_display = ("pk", "code", "name", "start_date", "end_date", "created_by")
    search_fields = [
        "name",
        "code",
    ]
    raw_id_fields = ("created_by",)
    readonly_fields = ("created_by", "created_at")
    inlines = (PkSupportRemarkInline,)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user

        if not models.Commune.objects.filter(code=form.cleaned_data["code"]).exists():
            messages.error(
                request,
                "Le code INSEE n'existe pas encore dans la table. "
                "Les fiches salarié utilisant ce code seront probablement rejetée par l'ASP.",
            )
        super().save_model(request, obj, form, change)


@admin.register(models.Department)
class DepartmentAdmin(ASPModelAdmin):
    pass


@admin.register(models.Country)
class CountryAdmin(ItouModelAdmin):
    list_display = ("pk", "code", "name")
    readonly_fields = ("pk",)
    ordering = ("name",)
    list_filter = (CountryFilter,)
