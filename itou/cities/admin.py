from django.contrib import admin
from django.contrib.gis import forms as gis_forms
from django.contrib.gis.db import models as gis_models

from itou.cities import models
from itou.geo.models import ZRR


@admin.register(models.City)
class CityAdmin(admin.ModelAdmin):
    list_display = ("name", "department", "post_codes", "code_insee")

    list_filter = ("department",)

    search_fields = ("name", "department", "post_codes", "code_insee")

    formfield_overrides = {
        # https://docs.djangoproject.com/en/2.2/ref/contrib/gis/forms-api/#widget-classes
        gis_models.PointField: {"widget": gis_forms.OSMWidget(attrs={"map_width": 800, "map_height": 500})}
    }

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
