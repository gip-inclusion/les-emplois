from django.contrib import admin

from itou.siaes import models


class MembersInline(admin.TabularInline):
    model = models.Siae.members.through
    extra = 1
    raw_id_fields = ('user',)


class JobsInline(admin.TabularInline):
    model = models.Siae.jobs.through
    extra = 1
    raw_id_fields = ('appellation',)


@admin.register(models.Siae)
class SiaeAdmin(admin.ModelAdmin):
    list_display = ('siret', 'kind', 'name', 'department', 'geocoding_score',)
    list_filter = ('kind', 'department',)
    search_fields = ('siret', 'name',)
    inlines = (MembersInline, JobsInline,)
