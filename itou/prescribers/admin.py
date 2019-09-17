from django.contrib import admin
from django.utils.translation import ugettext as _

from itou.prescribers import models


class MembersInline(admin.TabularInline):
    model = models.PrescriberOrganization.members.through
    extra = 1
    raw_id_fields = ("user",)


@admin.register(models.PrescriberOrganization)
class PrescriberOrganizationAdmin(admin.ModelAdmin):
    list_display = ("siret", "name")
    fieldsets = (
        (_("Structure"), {"fields": ("siret", "name", "phone", "email")}),
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
    search_fields = ("siret", "name")
    inlines = (MembersInline,)
