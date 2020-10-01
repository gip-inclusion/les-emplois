from django.contrib import admin
from django.utils.translation import gettext as _

from .models import PrescriberWithOrgInvitation, SiaeStaffInvitation


class IsValidFilter(admin.SimpleListFilter):
    title = _("En cours de validité")
    parameter_name = "is_valid"

    def lookups(self, request, model_admin):
        return (("yes", _("Oui")), ("no", _("Non")))

    def queryset(self, request, queryset):
        value = self.value()
        if value == "yes":
            return queryset.valid()
        if value == "no":
            return queryset.expired()
        return queryset


class BaseInvitationAdmin(admin.ModelAdmin):
    date_hierarchy = "sent_at"
    list_display = ("email", "first_name", "last_name", "sender", "sent_at", "is_valid", "accepted")
    ordering = ("-sent_at",)
    search_fields = ("email", "sender__email")
    # https://code.djangoproject.com/ticket/30354
    list_filter = ("accepted", IsValidFilter)
    readonly_fields = ("is_valid", "created_at", "sent_at", "accepted_at")
    raw_id_fields = ("sender",)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("sender")

    def is_valid(self, obj):
        return not obj.has_expired

    is_valid.boolean = True
    is_valid.short_description = _("En cours de validité")


@admin.register(SiaeStaffInvitation)
class SiaeStaffInvitationAdmin(BaseInvitationAdmin):
    list_display = BaseInvitationAdmin.list_display + ("siae",)
    raw_id_fields = BaseInvitationAdmin.raw_id_fields + ("siae",)
    search_fields = BaseInvitationAdmin.search_fields + ("siae__siret",)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("siae")


@admin.register(PrescriberWithOrgInvitation)
class PrescriberWithOrgInvitationAdmin(BaseInvitationAdmin):
    list_display = BaseInvitationAdmin.list_display + ("organization",)
    raw_id_fields = BaseInvitationAdmin.raw_id_fields + ("organization",)
    search_fields = BaseInvitationAdmin.search_fields + ("organization__siret",)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("organization")
