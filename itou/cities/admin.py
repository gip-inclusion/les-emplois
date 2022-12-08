from django.contrib import admin

from itou.cities import models
from itou.geo.models import ZRR
from itou.utils.admin import ItouGISMixin


@admin.register(models.City)
class CityAdmin(ItouGISMixin, admin.ModelAdmin):
    list_display = ("name", "department", "post_codes", "code_insee")

    list_filter = ("department",)

    search_fields = ("name", "department", "post_codes", "code_insee")

    readonly_fields = ("zrr",)

    fields = ("name", "department", "post_codes", "code_insee", "zrr", "coords")

    @admin.display(description="Commune en ZRR")
    def zrr(self, obj):
        # DO NOT USE THIS DYNAMIC FIELD IN 'list_display'
        try:
            zrr = ZRR.objects.get(insee_code=obj.code_insee)
        except ZRR.DoesNotExist:
            return "Impossible de déterminer la classification en ZRR"
        else:
            return zrr.get_status_display()
