from django.contrib import admin
from django.db.models import Count
from django.utils.translation import gettext as _

from itou.prescribers import models


class HasMembersFilter(admin.SimpleListFilter):
    title = _("A des membres")
    parameter_name = "has_members"

    def lookups(self, request, model_admin):
        return (("yes", _("Oui")), ("no", _("Non")))

    def queryset(self, request, queryset):
        value = self.value()
        if value == "yes":
            return queryset.filter(_member_count__gt=0)
        if value == "no":
            return queryset.exclude(_member_count__gt=0)
        return queryset


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
    list_display = ("id", "name", "post_code", "city", "department", "member_count")
    list_display_links = ("id", "name")
    list_filter = (HasMembersFilter, "is_authorized", "department")
    readonly_fields = ("secret_code",)
    search_fields = ("siret", "name")

    def member_count(self, obj):
        return obj._member_count

    member_count.admin_order_field = "_member_count"

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.annotate(_member_count=Count("members", distinct=True))
        return queryset

    def save_model(self, request, obj, form, change):
        if not obj.geocoding_score:
            obj.set_coords(obj.address_on_one_line, post_code=obj.post_code)
        super().save_model(request, obj, form, change)
