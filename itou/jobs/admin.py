from django.contrib import admin

from itou.jobs import models


@admin.register(models.Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ('code_rome', 'name',)
    list_filter = ('riasec_major', 'riasec_minor',)
    search_fields = ('code_rome', 'name',)

@admin.register(models.Appellation)
class AppellationAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'short_name',)
    search_fields = ('code', 'name', 'short_name',)
    raw_id_fields = ('job',)
