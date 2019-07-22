from django.contrib import admin

from itou.siae.models import Siae


@admin.register(Siae)
class SiaeAdmin(admin.ModelAdmin):
    list_display = ('siret', 'kind', 'name',)
    search_fields = ('siret', 'name',)
