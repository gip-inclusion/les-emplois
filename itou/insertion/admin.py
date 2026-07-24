import uuid

from django.contrib import admin
from django.db.models import Count, OuterRef, Subquery
from django.db.models.functions import Coalesce

from itou.insertion.models import (
    GenericReferenceItem,
    MobilizationEvent,
    Orientation,
    Service,
    Structure,
)
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
    list_display = ["pk", "name", "siret", "source", "city", "services_count", "is_active", "updated_at"]
    list_display_links = ["pk", "name"]
    list_filter = ["source", "is_active"]
    list_select_related = ["source"]
    show_full_result_count = False
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
        ("Horaires", {"fields": ["opening_hours"]}),
        ("État", {"fields": ["is_active"]}),
        ("Dates", {"fields": ["updated_on", "created_at", "updated_at"]}),
    ]

    def get_queryset(self, request):
        services_count = (
            Service.all_objects.filter(structure=OuterRef("pk"))
            .values("structure")
            .annotate(count=Count("pk"))
            .values("count")
        )
        return Structure.all_objects.select_related(*self.list_select_related).annotate(
            _services_count=Coalesce(Subquery(services_count), 0)
        )

    @admin.display(description="services", ordering="_services_count")
    def services_count(self, obj):
        return obj._services_count


@admin.register(Service)
class ServiceAdmin(InsertionAdmin):
    list_display = ["pk", "name", "structure_link", "source", "kind", "city", "is_active", "updated_at"]
    list_display_links = ["pk", "name"]
    list_filter = ["source", "kind", "is_orientable_with_form", "contact_is_public", "is_active"]
    list_select_related = ["structure", "source", "kind"]
    show_full_result_count = False
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
                    "eligibility_zones",
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
        ("État", {"fields": ["is_active"]}),
        ("Dates", {"fields": ["dora_synced_at", "updated_on", "created_at", "updated_at"]}),
    ]

    def get_queryset(self, request):
        return Service.all_objects.select_related(*self.list_select_related)

    @admin.display(description="structure")
    def structure_link(self, obj):
        return get_admin_view_link(obj.structure, content=obj.structure.name)


@admin.register(MobilizationEvent)
class MobilizationEventAdmin(InsertionAdmin):
    list_display = [
        "pk",
        "kind",
        "service__name",
        "structure__name",
        "user",
        "prescriber_organization",
        "company",
        "created_at",
    ]
    list_display_links = ["pk", "kind"]
    list_select_related = ["structure", "service"]
    list_filter = ["kind"]
    ordering = ["-created_at"]
    show_full_result_count = False

    fields = readonly_fields = [
        "pk",
        "kind",
        "user",
        "service_link",
        "structure_link",
        "prescriber_organization_link",
        "company_link",
        "service_external_link",
        "created_at",
    ]

    @admin.display(description="structure")
    def structure_link(self, obj):
        return get_admin_view_link(obj.structure, content=obj.structure.name)

    @admin.display(description="service")
    def service_link(self, obj):
        return get_admin_view_link(obj.service, content=obj.service.name)

    @admin.display(description="organisation prescriptrice")
    def prescriber_organization_link(self, obj):
        return get_admin_view_link(obj.prescriber_organization, content=obj.prescriber_organization.name)

    @admin.display(description="entreprise")
    def company_link(self, obj):
        return get_admin_view_link(obj.company, content=obj.company.name)


@admin.register(Orientation)
class OrientationAdmin(InsertionAdmin):
    list_display = [
        "pk",
        "status",
        "beneficiary",
        "service",
        "sender_organization_display",
        "created_at",
    ]
    list_filter = ["status", "sender_kind", "created_at"]
    list_select_related = [
        "beneficiary",
        "sender",
        "sender_prescriber_organization",
        "sender_company",
        "service",
        "service__structure",
    ]
    ordering = ["-created_at"]
    fieldsets = [
        (
            "Orientation",
            {
                "fields": [
                    "status",
                    "beneficiary",
                    "service",
                    "duration_weekly_hours",
                    "duration_weeks",
                    "data_protection_commitment",
                ]
            },
        ),
        (
            "Origine",
            {
                "fields": [
                    "sender",
                    "sender_kind",
                    "sender_company",
                    "sender_prescriber_organization",
                ]
            },
        ),
        (
            "Bénéficiaire",
            {
                "fields": [
                    "beneficiary_contact_preferences",
                    "beneficiary_other_contact_method",
                    "beneficiary_availability",
                    "requirements",
                    "situation",
                    "situation_other",
                ]
            },
        ),
        (
            "Référent",
            {
                "fields": [
                    "referent_first_name",
                    "referent_last_name",
                    "referent_email",
                    "referent_phone",
                    "orientation_reasons",
                ]
            },
        ),
        (
            "Audit",
            {
                "fields": [
                    "processing_date",
                    "created_at",
                    "updated_at",
                ]
            },
        ),
    ]

    def get_search_fields(self, request):
        search_fields = []
        search_term = request.GET.get("q", "").strip()
        try:
            uuid.UUID(search_term)
        except (TypeError, ValueError):
            pass
        else:
            search_fields.append("pk__exact")

        return search_fields or ["status__startswith"]

    @admin.display(description="structure émettrice")
    def sender_organization_display(self, obj):
        organization = obj.sender_organization
        return organization.name if organization else "—"
