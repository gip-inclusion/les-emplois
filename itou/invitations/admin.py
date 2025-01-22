from django.contrib import admin

from itou.invitations.models import EmployerInvitation, LaborInspectorInvitation, PrescriberWithOrgInvitation
from itou.utils.admin import ItouModelAdmin


class IsValidFilter(admin.SimpleListFilter):
    title = "en cours de validité"
    parameter_name = "is_valid"

    def lookups(self, request, model_admin):
        return (("yes", "Oui"), ("no", "Non"))

    def queryset(self, request, queryset):
        value = self.value()
        if value == "yes":
            return queryset.valid()
        if value == "no":
            return queryset.expired()
        return queryset


class AcceptedFilter(admin.SimpleListFilter):
    title = "acceptée"
    parameter_name = "accepted"

    def lookups(self, request, model_admin):
        return (("yes", "Oui"), ("no", "Non"))

    def queryset(self, request, queryset):
        value = self.value()
        if value == "yes":
            return queryset.filter(accepted_at__isnull=False)
        if value == "no":
            return queryset.filter(accepted_at=None)
        return queryset


class BaseInvitationAdmin(ItouModelAdmin):
    date_hierarchy = "sent_at"
    list_display = ("email", "first_name", "last_name", "sender", "sent_at", "is_valid", "accepted")
    ordering = ("-sent_at",)
    search_fields = ("email", "sender__email")
    # https://code.djangoproject.com/ticket/30354
    list_filter = (AcceptedFilter, IsValidFilter)
    readonly_fields = ("is_valid", "created_at", "sent_at", "accepted_at", "acceptance_link")
    raw_id_fields = ("sender",)
    list_select_related = ("sender",)

    @admin.display(boolean=True, description="en cours de validité")
    def is_valid(self, obj):
        return not obj.has_expired

    @admin.display(boolean=True, description="acceptée")
    def accepted(self, obj):
        return obj.accepted_at is not None

    @admin.display(description="lien")
    def acceptance_link(self, obj):
        return obj.acceptance_link


@admin.register(EmployerInvitation)
class EmployerInvitationAdmin(BaseInvitationAdmin):
    list_display = BaseInvitationAdmin.list_display + ("company",)
    raw_id_fields = BaseInvitationAdmin.raw_id_fields + ("company",)
    search_fields = BaseInvitationAdmin.search_fields + ("company__siret",)
    list_select_related = BaseInvitationAdmin.list_select_related + ("company",)


@admin.register(PrescriberWithOrgInvitation)
class PrescriberWithOrgInvitationAdmin(BaseInvitationAdmin):
    list_display = BaseInvitationAdmin.list_display + ("organization",)
    raw_id_fields = BaseInvitationAdmin.raw_id_fields + ("organization",)
    search_fields = BaseInvitationAdmin.search_fields + ("organization__siret",)
    list_select_related = BaseInvitationAdmin.list_select_related + ("organization",)


@admin.register(LaborInspectorInvitation)
class LaborInspectorInvitationAdmin(BaseInvitationAdmin):
    list_display = BaseInvitationAdmin.list_display + ("institution",)
    raw_id_fields = BaseInvitationAdmin.raw_id_fields + ("institution",)
    search_fields = BaseInvitationAdmin.search_fields + ("institution__name",)
    list_select_related = BaseInvitationAdmin.list_select_related + ("institution",)
