from django.contrib import admin
from django.db.models import Count
from django.utils.translation import ugettext as _

from itou.siaes import models


class MembersInline(admin.TabularInline):
    model = models.Siae.members.through
    extra = 1
    raw_id_fields = ("user",)


class JobsInline(admin.TabularInline):
    model = models.Siae.jobs.through
    extra = 1
    raw_id_fields = ("appellation",)


class SiaeHasMembersFilter(admin.SimpleListFilter):
    title = _("A des membres")
    parameter_name = "has_members"

    def lookups(self, request, model_admin):
        return (("yes", _("Oui")), ("no", _("Non")))

    def queryset(self, request, queryset):
        value = self.value()
        if value == "yes":
            return queryset.filter(_member_count__gt=0)
        return queryset.exclude(_member_count__gt=0)


@admin.register(models.Siae)
class SiaeAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "siret",
        "kind",
        "name",
        "department",
        "geocoding_score",
        "member_count",
    )
    list_filter = ("kind", "department", SiaeHasMembersFilter)
    fieldsets = (
        (
            _("SIAE"),
            {
                "fields": (
                    "siret",
                    "naf",
                    "kind",
                    "name",
                    "brand",
                    "phone",
                    "email",
                    "website",
                    "description",
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
    search_fields = ("siret", "name")
    inlines = (MembersInline, JobsInline)

    def member_count(self, obj):
        return obj._member_count

    member_count.admin_order_field = "_member_count"

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.annotate(_member_count=Count("members", distinct=True))
        return queryset


@admin.register(models.SiaeJobDescription)
class SiaeJobDescription(admin.ModelAdmin):
    list_display = (
        "appellation",
        "siae",
        "created_at",
        "updated_at",
        "is_active",
        "custom_name",
    )
    raw_id_fields = ("appellation", "siae")
