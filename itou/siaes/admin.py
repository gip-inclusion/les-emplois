from django.contrib import admin, messages
from django.db.models import Count
from django.utils.translation import gettext as _

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
        if value == "no":
            return queryset.exclude(_member_count__gt=0)
        return queryset


@admin.register(models.Siae)
class SiaeAdmin(admin.ModelAdmin):
    list_display = ("id", "siret", "kind", "name", "department", "geocoding_score", "member_count")
    list_filter = (SiaeHasMembersFilter, "kind", "source", "department")
    raw_id_fields = ("created_by",)
    readonly_fields = ("created_by", "created_at", "updated_at")
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
                    "auth_email",
                    "website",
                    "description",
                    "source",
                    "created_by",
                    "created_at",
                    "updated_at",
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
    search_fields = ("id", "siret", "name")
    inlines = (MembersInline, JobsInline)

    def member_count(self, obj):
        return obj._member_count

    member_count.admin_order_field = "_member_count"

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.annotate(_member_count=Count("members", distinct=True))
        return queryset

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        form.base_fields["source"].initial = models.Siae.SOURCE_USER_CREATED
        return form

    def save_model(self, request, obj, form, change):
        if not obj.pk:
            obj.created_by = request.user
        if not obj.geocoding_score:
            obj.set_coords(obj.address_on_one_line, post_code=obj.post_code)
        if not obj.auth_email:
            messages.warning(
                request, "Cette structure n'ayant pas d'email d'authentification il est impossible de s'y inscrire."
            )
        super().save_model(request, obj, form, change)


@admin.register(models.SiaeJobDescription)
class SiaeJobDescription(admin.ModelAdmin):
    list_display = ("appellation", "siae", "created_at", "updated_at", "is_active", "custom_name")
    raw_id_fields = ("appellation", "siae")
