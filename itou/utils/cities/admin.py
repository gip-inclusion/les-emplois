from django.contrib import admin

from itou.utils.cities import models


@admin.register(models.City)
class CityAdmin(admin.ModelAdmin):
    list_display = ('name', 'department', 'post_codes', 'code_insee',)
    list_filter = ('department',)
    search_fields = ('name', 'department', 'post_codes', 'code_insee',)
