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


class AuthorizationValidationRequired(admin.SimpleListFilter):
    title = _("Validation de l'habilitation requise")
    parameter_name = "authorization_validation_required"

    def lookups(self, request, model_admin):
        return (("required", _("Requise")),)

    def queryset(self, request, queryset):
        if self.value() == "required":
            return queryset.filter(
                authorization_status=models.PrescriberOrganization.AuthorizationStatus.NOT_SET, _member_count__gt=0
            )
        return queryset


class MembersInline(admin.TabularInline):
    model = models.PrescriberOrganization.members.through
    extra = 1
    raw_id_fields = ("user",)


@admin.register(models.PrescriberOrganization)
class PrescriberOrganizationAdmin(admin.ModelAdmin):
    class Media:
        css = {"all": ("css/itou-admin.css",)}

    change_form_template = "admin/prescribers/change_form.html"

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
                    "code_safir_pole_emploi",
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
        (
            _("Info"),
            {
                "fields": (
                    "created_by",
                    "created_at",
                    "updated_at",
                    "authorization_status",
                    "authorization_updated_at",
                    "authorization_updated_by",
                )
            },
        ),
    )
    inlines = (MembersInline,)
    list_display = ("pk", "name", "post_code", "city", "department", "member_count")
    list_display_links = ("pk", "name")
    list_filter = (AuthorizationValidationRequired, HasMembersFilter, "is_authorized", "kind", "department")
    raw_id_fields = ("created_by",)
    readonly_fields = (
        "secret_code",
        "code_safir_pole_emploi",
        "created_by",
        "created_at",
        "updated_at",
        "is_authorized",
        "authorization_status",
        "authorization_updated_at",
        "authorization_updated_by",
    )
    search_fields = ("pk", "siret", "name", "code_safir_pole_emploi")

    def member_count(self, obj):
        return obj._member_count

    member_count.admin_order_field = "_member_count"

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.annotate(_member_count=Count("members", distinct=True))
        return queryset

    def save_model(self, request, obj, form, change):

        if not change:
            obj.created_by = request.user
            if not obj.geocoding_score and obj.address_on_one_line:
                # Set geocoding.
                obj.set_coords(obj.address_on_one_line, post_code=obj.post_code)

        if change and obj.address_on_one_line:
            old_obj = self.model.objects.get(id=obj.id)
            if obj.address_on_one_line != old_obj.address_on_one_line:
                # Refresh geocoding.
                obj.set_coords(obj.address_on_one_line, post_code=obj.post_code)

        super().save_model(request, obj, form, change)

    def response_change(self, request, obj):
        # Override for custom "actions" in the admin change form for:
        # * refusing authorization
        # * validating authorization

        if "_authorization_action_refuse" in request.POST:
            obj.is_authorized = False
            obj.authorization_status = models.PrescriberOrganization.AuthorizationStatus.REFUSED
            obj.authorization_updated_at = now()
            obj.authorization_updated_by = request.user
            obj.save()
            obj.refused_prescriber_organization_email().send()

        if "_authorization_action_validate" in request.POST:
            obj.is_authorized = True
            obj.authorization_status = models.PrescriberOrganization.AuthorizationStatus.VALIDATED
            obj.authorization_updated_at = now()
            obj.authorization_updated_by = request.user
            obj.save()
            obj.validated_prescriber_organization_email().send()

        return super().response_change(request, obj)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        obj = models.PrescriberOrganization.objects.get(pk=object_id)
        extra_context = extra_context or {}
        extra_context["authorization_validation_required"] = (
            obj.authorization_status == models.PrescriberOrganization.AuthorizationStatus.NOT_SET
        )
        return super().change_view(request, object_id, form_url, extra_context)
