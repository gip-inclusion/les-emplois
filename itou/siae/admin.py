from django.contrib import admin

from itou.siae import models


class MembersInline(admin.TabularInline):
    model = models.Siae.members.through
    extra = 1
    raw_id_fields = ('user',)


@admin.register(models.Siae)
class SiaeAdmin(admin.ModelAdmin):
    list_display = ('siret', 'kind', 'name', 'geocoding_score',)
    list_filter = ('kind', 'department',)
    search_fields = ('siret', 'name',)
    inlines = (MembersInline,)
