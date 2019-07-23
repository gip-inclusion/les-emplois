from django.contrib import admin

from itou.prescribers import models


class MembersInline(admin.TabularInline):
    model = models.Prescriber.members.through
    extra = 1
    raw_id_fields = ('user',)


@admin.register(models.Prescriber)
class PrescriberAdmin(admin.ModelAdmin):
    list_display = ('siret', 'name',)
    search_fields = ('siret', 'name',)
    inlines = (MembersInline,)
