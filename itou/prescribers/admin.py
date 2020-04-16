from django.contrib import admin
from django.db.models import Count
from django.utils.timezone import now
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
                    "kind",
                    "name",
                    "phone",
                    "email",
                    "secret_code",
                    "is_authorized",
                    "authorization_is_validated",
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
        (
            _("Info"),
            {
                "fields": (
                    "created_by",
                    "created_at",
                    "updated_at",
                    "authorization_validated_at",
                    "authorization_validated_by",
                )
            },
        ),
    )
    inlines = (MembersInline,)
    list_display = ("id", "name", "post_code", "city", "department", "member_count")
    list_display_links = ("id", "name")
    list_filter = ("authorization_is_validated", HasMembersFilter, "is_authorized", "kind", "department")
    raw_id_fields = ("created_by",)
    readonly_fields = (
        "secret_code",
        "created_by",
        "created_at",
        "updated_at",
        "authorization_validated_at",
        "authorization_validated_by",
    )
    search_fields = ("siret", "name")

    def member_count(self, obj):
        return obj._member_count

    member_count.admin_order_field = "_member_count"

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.annotate(_member_count=Count("members", distinct=True))
        return queryset

    def save_model(self, request, obj, form, change):
        if not obj.pk:
            obj.created_by = request.user
        if not obj.geocoding_score and obj.address_on_one_line:
            obj.set_coords(obj.address_on_one_line, post_code=obj.post_code)
        if obj.authorization_is_validated and not obj.authorization_validated_at:
            # Validation of the authorization & created at/by
            obj.authorization_validated_at = now()
            obj.authorization_validated_by = request.user
            obj.validated_prescriber_organization_email().send()

        super().save_model(request, obj, form, change)
