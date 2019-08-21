from django.contrib import admin

from itou.jobs import models


class AppellationsInline(admin.TabularInline):
    model = models.Appellation
    readonly_fields = ('code', 'name',)
    can_delete = False

    def has_add_permission(self, request):
        return False


@admin.register(models.Rome)
class RomeAdmin(admin.ModelAdmin):
    list_display = ('code', 'name',)
    list_filter = ('riasec_major', 'riasec_minor',)
    search_fields = ('code', 'name',)
    inlines = (AppellationsInline,)


@admin.register(models.Appellation)
class AppellationAdmin(admin.ModelAdmin):
    list_display = ('code', 'name',)
    search_fields = ('code', 'name',)
    raw_id_fields = ('rome',)
