from django.contrib import admin

from itou.cities import models
from itou.geo.models import ZRR
from itou.utils.admin import ItouGISMixin, ItouModelAdmin, ReadonlyMixin


@admin.register(models.City)
class CityAdmin(ReadonlyMixin, ItouGISMixin, ItouModelAdmin):
    list_display = ("name", "department", "post_codes", "code_insee", "siren_epci")

    list_filter = ("department",)

    search_fields = (
        "name__istartswith",
        "department__exact",
        "code_insee__iexact",
        "siren_epci__istartswith",
    )

    readonly_fields = ("zrr", "edition_mode")

    def get_search_results(self, request, queryset, search_term):
        # The default admin search casts ArrayField to text, so "75" also matches "01750".
        # This override forces postcodes search to be performed as ArrayField.
        base_queryset = queryset
        queryset, may_have_duplicates = super().get_search_results(request, queryset, search_term)
        search_term = search_term.strip()
        if len(search_term) == 5 and search_term.isdecimal():
            queryset |= base_queryset.filter(post_codes__contains=[search_term])
        return queryset, may_have_duplicates

    fields = (
        "name",
        "department",
        "post_codes",
        "code_insee",
        "siren_epci",
        "zrr",
        "coords",
        "edition_mode",
    )

    @admin.display(description="commune en ZRR")
    def zrr(self, obj):
        # DO NOT USE THIS DYNAMIC FIELD IN 'list_display'
        try:
            zrr = ZRR.objects.get(insee_code=obj.code_insee)
        except ZRR.DoesNotExist:
            return "Impossible de déterminer la classification en ZRR"
        else:
            return zrr.get_status_display()


@admin.register(models.DirectoryActiveCity)
class DirectoryActiveCityAdmin(ItouModelAdmin):
    list_display = ("city",)
    autocomplete_fields = ("city",)
    search_fields = ("city__name__istartswith", "city__code_insee__iexact")
