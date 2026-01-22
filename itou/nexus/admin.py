from django.conf import settings
from django.contrib import admin

from itou.nexus.models import ActivatedService, NexusMembership, NexusRessourceSyncStatus, NexusStructure, NexusUser
from itou.utils.admin import ItouGISMixin, ItouModelAdmin, ItouTabularInline, ReadonlyMixin, get_admin_view_link
from itou.utils.enums import ItouEnvironment


class NexusAdminMixin:
    def get_queryset(self, request):
        qs = self.model.include_old.with_threshold()
        ordering = self.get_ordering(request)
        if ordering:
            qs = qs.order_by(*ordering)
        return qs

    @admin.display(boolean=True)
    def is_active(self, obj):
        if not obj.pk:
            return None
        return obj.updated_at > obj.threshold


class NexusMembersUserInline(NexusAdminMixin, ReadonlyMixin, ItouTabularInline):
    list_select_related = ("structure",)
    show_change_link = True
    model = NexusMembership
    fields = ("structure_link", "role", "updated_at", "is_active")
    ordering = ("structure__name",)
    readonly_fields = ("structure_link", "updated_at", "is_active")

    def structure_link(self, obj):
        return get_admin_view_link(
            obj.structure, content=f"{obj.structure.name} – {obj.structure.kind} – {obj.structure.siret}"
        )


@admin.register(NexusUser)
class NexusUserAdmin(NexusAdminMixin, ItouModelAdmin):
    list_display = (
        "email",
        "first_name",
        "last_name",
        "source",
        "updated_at",
        "is_active",
    )
    list_filter = ("source",)
    fieldsets = (
        (
            "Utilisateur",
            {
                "fields": (
                    "id",
                    "source",
                    "first_name",
                    "last_name",
                    "email",
                    "phone",
                    "kind",
                )
            },
        ),
        (
            "Audit",
            {
                "fields": (
                    "source_kind",
                    "source_id",
                    "last_login",
                    "updated_at",
                    "is_active",
                ),
            },
        ),
    )
    readonly_fields = ("updated_at", "is_active")
    inlines = (NexusMembersUserInline,)


class NexusMembersStructureInline(NexusAdminMixin, ReadonlyMixin, ItouTabularInline):
    list_select_related = ("user",)
    show_change_link = True
    model = NexusMembership
    fields = ("user_link", "role", "updated_at", "is_active")
    ordering = ("user__last_name", "user__first_name")
    readonly_fields = ("user_link", "updated_at", "is_active")

    def user_link(self, obj):
        return get_admin_view_link(obj.user, content=obj.user.display_with_pii)


@admin.register(NexusStructure)
class NexusStructureAdmin(NexusAdminMixin, ItouGISMixin, ItouModelAdmin):
    list_display = (
        "name",
        "siret",
        "kind",
        "source",
        "updated_at",
        "is_active",
    )
    list_filter = ("source",)
    raw_id_fields = ("insee_city",)
    readonly_fields = ("id", "updated_at", "is_active")
    fieldsets = (
        (
            "Entreprise",
            {
                "fields": (
                    "id",
                    "source",
                    "siret",
                    "kind",
                    "name",
                    "phone",
                    "email",
                    "website",
                    "opening_hours",
                    "accessibility",
                    "description",
                )
            },
        ),
        (
            "Audit",
            {
                "fields": (
                    "source_kind",
                    "source_id",
                    "updated_at",
                    "is_active",
                    "source_link",
                ),
            },
        ),
        (
            "Adresse",
            {
                "fields": (
                    "address_line_1",
                    "address_line_2",
                    "post_code",
                    "city",
                    "department",
                    "coords",
                    "geocoding_score",
                )
            },
        ),
    )
    inlines = (NexusMembersStructureInline,)


if settings.ITOU_ENVIRONMENT != ItouEnvironment.PROD:

    @admin.register(NexusMembership)
    class NexusMembershipAdmin(NexusAdminMixin, ItouModelAdmin):
        # Only for testing purpose, to manually add memberships
        list_filter = ("source",)
        list_display = (
            "id",
            "user_link",
            "structure_link",
            "role",
            "source",
            "updated_at",
            "is_active",
        )
        raw_id_fields = ("user", "structure")
        fields = ("source", "user", "structure", "role", "updated_at", "is_active")
        readonly_fields = ("updated_at", "is_active")

        def user_link(self, obj):
            return get_admin_view_link(obj.user)

        def structure_link(self, obj):
            return get_admin_view_link(obj.structure)


@admin.register(NexusRessourceSyncStatus)
class NexusRessourceSyncStatusAdmin(ItouModelAdmin):
    list_display = ("service", "valid_since", "in_progress_since")


@admin.register(ActivatedService)
class ActivatedServiceAdmin(ItouModelAdmin):
    list_display = ("user", "service", "created_at")
