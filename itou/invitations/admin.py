from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _

from .models import Invitation


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    date_hierarchy = "sent_at"
    list_display = ("first_name", "last_name", "sender_name", "sent_at")

    # https://code.djangoproject.com/ticket/30354
    list_filter = ("accepted", ("sender", admin.RelatedOnlyFieldListFilter))
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
                ]
            },
        )
    ]

    def sender_name(self, obj):
        return f"{obj.sender.get_full_name()}"

    sender_name.short_description = _("Parrain ou Marraine")

    def sender_link(self, obj):
        link = reverse("admin:users_user_change", kwargs={"object_id": obj.sender.pk})
        return format_html('<a href="{}">{}</a>', mark_safe(link), obj.sender.get_full_name())

    sender_link.short_description = _("Parrain ou Marraine")

    def has_expired(self, obj):
        value = _("Non")
        if obj.has_expired:
            value = _("Oui")
        return value

    has_expired.short_description = _("Expirée")
