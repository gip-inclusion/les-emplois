from django.contrib import admin
from django.utils.translation import ugettext as _

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
    fieldsets = (
        (
            _("SIAE"), {
                'fields': (
                    'siret',
                    'naf',
                    'kind',
                    'name',
                    'brand',
                    'phone',
                    'email',
                    'website',
                    'description',
                )
            }
        ),
        (
            _("Adresse"), {
                'fields': (
                    'address_line_1',
                    'address_line_2',
                    'post_code',
                    'city',
                    'department',
                    'coords',
                    'geocoding_score',
                )
            }
        ),
    )
    search_fields = ('siret', 'name',)
    inlines = (MembersInline, JobsInline,)
