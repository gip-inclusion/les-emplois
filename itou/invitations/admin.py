from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _

from .models import PrescriberWithOrgInvitation, SiaeStaffInvitation


class BaseInvitationAdmin(admin.ModelAdmin):
    date_hierarchy = "sent_at"
    list_display = ("first_name", "last_name", "sender_name", "sent_at")

    # https://code.djangoproject.com/ticket/30354
    list_filter = ("accepted",)
    readonly_fields = ("sender_link", "has_expired")
    fieldsets = [
        (
            None,
            {
                "fields": [
                    "first_name",
                    "last_name",
                    "email",
                    "sender_link",
                    "has_expired",
                    "sent",
                    "accepted",
                    "sent_at",
                    "accepted_at",
                ]
            },
        )
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("sender")

    def sender_name(self, obj):
        return f"{obj.sender.get_full_name()}"

    sender_name.short_description = _("Parrain ou Marraine")

    def sender_link(self, obj):
        link = reverse("admin:users_user_change", kwargs={"object_id": obj.sender.pk})
        return format_html('<a href="{}">{}</a>', mark_safe(link), obj.sender.get_full_name())

    sender_link.short_description = _("Parrain ou Marraine")

    def has_expired(self, obj):
        value = _("Non")
        if obj.sent_at:
            if obj.has_expired:
                value = _("Oui")
        return value

    has_expired.short_description = _("Expirée")


@admin.register(SiaeStaffInvitation)
class SiaeStaffInvitationAdmin(BaseInvitationAdmin):
    readonly_fields = BaseInvitationAdmin.readonly_fields + ("siae_link",)
    list_display = BaseInvitationAdmin.list_display + ("siae_name",)

    fieldsets = [
        (
            None,
            {
                "fields": [
                    "first_name",
                    "last_name",
                    "email",
                    "sender_link",
                    "siae_link",
                    "has_expired",
                    "sent",
                    "sent_at",
                    "accepted",
                    "accepted_at",
                ]
            },
        )
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("siae")

    def siae_link(self, obj):
        link = reverse("admin:siaes_siae_change", kwargs={"object_id": obj.siae.pk})
        return format_html('<a href="{}">{}</a>', mark_safe(link), obj.siae.display_name)

    siae_link.short_description = _("Structure")

    def siae_name(self, obj):
        return obj.siae.display_name

    siae_name.short_description = _("Structure")


@admin.register(PrescriberWithOrgInvitation)
class PrescriberWithOrgInvitationAdmin(BaseInvitationAdmin):
    readonly_fields = BaseInvitationAdmin.readonly_fields + ("org_link",)
    list_display = BaseInvitationAdmin.list_display + ("org_name",)

    fieldsets = [
        (
            None,
            {
                "fields": [
                    "first_name",
                    "last_name",
                    "email",
                    "sender_link",
                    "org_link",
                    "has_expired",
                    "sent",
                    "sent_at",
                    "accepted",
                    "accepted_at",
                ]
            },
        )
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("organization")

    def org_link(self, obj):
        link = reverse("admin:prescribers_prescriberorganization_change", kwargs={"object_id": obj.organization.pk})
        return format_html('<a href="{}">{}</a>', mark_safe(link), obj.organization.display_name)

    org_link.short_description = _("Organisation")

    def org_name(self, obj):
        return obj.organization.display_name

    org_name.short_description = _("Organisation")
