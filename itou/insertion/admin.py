from django.contrib import admin

from itou.insertion.models import GenericReferenceItem, Service, Structure
from itou.utils.admin import ItouModelAdmin, ItouTabularInline, ReadonlyMixin, get_admin_view_link


@admin.register(GenericReferenceItem)
class GenericReferenceItemAdmin(ReadonlyMixin, ItouModelAdmin):
    list_display = ["pk", "source", "kind", "value", "label", "created_at", "updated_at"]
    list_filter = ["source", "kind"]
    ordering = ["kind", "value"]
    search_fields = ["value", "label"]


class ServicesInline(ReadonlyMixin, ItouTabularInline):
    model = Service
    show_change_link = True
    fields = readonly_fields = ["uid", "name", "created_at", "updated_at"]
    ordering = ["uid"]


@admin.register(Structure)
class StructureAdmin(ReadonlyMixin, ItouModelAdmin):
    list_display = ["pk", "uid", "siret", "name", "created_at", "updated_at"]
    list_display_links = ["uid"]
    list_filter = ["source"]
    ordering = ["-updated_at", "-created_at"]
    search_fields = ["uid", "siret", "name"]
    inlines = [ServicesInline]


@admin.register(Service)
class ServiceAdmin(ReadonlyMixin, ItouModelAdmin):
    list_display = ["pk", "uid", "name", "structure_link", "created_at", "updated_at"]
    list_display_links = ["uid"]
    list_filter = ["source"]
    ordering = ["-updated_at", "-created_at"]
    search_fields = ["uid", "name"]

    @admin.display(description="structure")
    def structure_link(self, obj):
        return get_admin_view_link(obj.structure, content=obj.structure.name)
