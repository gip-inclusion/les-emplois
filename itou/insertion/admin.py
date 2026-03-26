from django.contrib import admin
from django.db.models import Count

from itou.insertion.models import GenericReferenceItem, Service, Structure
from itou.utils.admin import ItouModelAdmin, ItouTabularInline, ReadonlyMixin, get_admin_view_link


class InsertionAdmin(ReadonlyMixin, ItouModelAdmin):
    show_facets = admin.ShowFacets.ALWAYS

    extra_readonly_fields = ()

    def get_readonly_fields(self, request, obj=None):
        own_fields = [field.name for field in self.model._meta.fields + self.model._meta.many_to_many]
        return own_fields + list(self.extra_readonly_fields)


@admin.register(GenericReferenceItem)
class GenericReferenceItemAdmin(InsertionAdmin):
    list_display = ["pk", "kind", "value", "label", "source", "updated_at"]
    list_display_links = ["pk", "value"]
    list_filter = ["source", "kind"]
    ordering = ["kind", "value"]
    search_fields = ["value", "label", "description"]


class ServicesInline(ReadonlyMixin, ItouTabularInline):
    model = Service
    show_change_link = True
    fields = readonly_fields = ["uid", "name", "kind", "created_at", "updated_at"]
    ordering = ["uid"]


@admin.register(Structure)
class StructureAdmin(InsertionAdmin):
    list_display = ["pk", "name", "siret", "source", "city", "services_count", "updated_at"]
    list_display_links = ["pk", "name"]
    list_filter = ["source"]
    list_select_related = ["source"]
    date_hierarchy = "updated_on"
    ordering = ["-updated_at", "-created_at"]
    search_fields = ["uid", "siret", "name", "city", "post_code"]
    inlines = [ServicesInline]
    fieldsets = [
        ("Identification", {"fields": ["uid", "name", "siret", "source", "source_link"]}),
        ("Présentation", {"fields": ["description", "website"]}),
        ("Contact", {"fields": ["email", "phone"]}),
        (
            "Adresse",
            {"fields": ["address_line_1", "address_line_2", "post_code", "city", "insee_city", "coordinates"]},
        ),
        ("Dates", {"fields": ["updated_on", "created_at", "updated_at"]}),
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_services_count=Count("services"))

    @admin.display(description="services", ordering="_services_count")
    def services_count(self, obj):
        return obj._services_count


@admin.register(Service)
class ServiceAdmin(InsertionAdmin):
    list_display = ["pk", "name", "structure_link", "source", "kind", "city", "updated_at"]
    list_display_links = ["pk", "name"]
    list_filter = ["source", "kind", "is_orientable_with_form", "contact_is_public"]
    list_select_related = ["structure", "source", "kind"]
    date_hierarchy = "updated_on"
    ordering = ["-updated_at", "-created_at"]
    search_fields = ["uid", "name", "structure__name", "city"]
    extra_readonly_fields = ["structure_link"]
    fieldsets = [
        ("Identification", {"fields": ["uid", "name", "structure_link", "source", "source_link"]}),
        ("Présentation", {"fields": ["description_short", "description", "kind", "thematics"]}),
        (
            "Publics & accès",
            {
                "fields": [
                    "publics",
                    "publics_details",
                    "access_conditions_di",
                    "access_conditions_dora",
                    "receptions",
                    "fee",
                    "fee_details",
                ]
            },
        ),
        (
            "Mobilisation (data·inclusion)",
            {"fields": ["mobilizations", "mobilizations_details", "mobilization_publics"]},
        ),
        (
            "Mobilisation (DORA)",
            {
                "fields": [
                    "mobilization_modes_beneficiaries",
                    "mobilization_modes_beneficiaries_external_form_link",
                    "mobilization_modes_beneficiaries_external_form_link_text",
                    "mobilization_modes_beneficiaries_other",
                    "mobilization_modes_professionals",
                    "mobilization_modes_professionals_external_form_link",
                    "mobilization_modes_professionals_external_form_link_text",
                    "mobilization_modes_professionals_other",
                    "funding_labels",
                ]
            },
        ),
        ("Justificatifs", {"fields": ["credentials", "credentials_documents", "credentials_online_form"]}),
        (
            "Adresse",
            {"fields": ["address_line_1", "address_line_2", "post_code", "city", "insee_city", "coordinates"]},
        ),
        ("Contact", {"fields": ["contact_full_name", "contact_email", "contact_phone", "contact_is_public"]}),
        ("Horaires", {"fields": ["opening_hours", "opening_hours_text"]}),
        ("Orientation", {"fields": ["is_orientable_with_form", "average_orientation_response_delay_days"]}),
        ("Dates", {"fields": ["dora_synced_at", "updated_on", "created_at", "updated_at"]}),
    ]

    @admin.display(description="structure")
    def structure_link(self, obj):
        return get_admin_view_link(obj.structure, content=obj.structure.name)
