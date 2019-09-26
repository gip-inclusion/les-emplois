from django.contrib import admin
from django.utils.translation import ugettext as _

from itou.prescribers import models


class MembersInline(admin.TabularInline):
    model = models.PrescriberOrganization.members.through
    extra = 1
    raw_id_fields = ("user",)


@admin.register(models.PrescriberOrganization)
class PrescriberOrganizationAdmin(admin.ModelAdmin):
    fieldsets = (
        (
            _("Structure"),
            {
                "fields": (
                    "siret",
                    "name",
                    "phone",
                    "email",
                    "secret_code",
                    "is_authorized",
                )
            },
        ),
        (
            _("Adresse"),
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
    inlines = (MembersInline,)
    list_display = ("siret", "name")
    list_filter = ("is_authorized",)
    readonly_fields = ("secret_code",)
    search_fields = ("siret", "name")
