from django.contrib import admin

from itou.cities import models
from itou.geo.models import ZRR
from itou.utils.admin import ItouGISMixin, ItouModelAdmin, ReadonlyMixin


@admin.register(models.City)
class CityAdmin(ReadonlyMixin, ItouGISMixin, ItouModelAdmin):
    list_display = ("name", "department", "post_codes", "code_insee", "siren_epci")

    list_filter = ("department",)

    search_fields = ("name", "department", "post_codes", "code_insee", "siren_epci")

    readonly_fields = ("zrr", "edition_mode")

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
