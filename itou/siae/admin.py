from django.contrib import admin

from itou.siae import models


class MembersInline(admin.TabularInline):
    model = models.Siae.members.through
    extra = 1
    raw_id_fields = ('user',)


class JobAppellationsInline(admin.TabularInline):
    model = models.Siae.job_appellations.through
    extra = 1
    raw_id_fields = ('appellation',)


@admin.register(models.Siae)
class SiaeAdmin(admin.ModelAdmin):
    list_display = ('siret', 'kind', 'name', 'department', 'geocoding_score',)
    list_filter = ('kind', 'department',)
    search_fields = ('siret', 'name',)
    exclude = ('job_appellations',)
    inlines = (MembersInline, JobAppellationsInline,)
