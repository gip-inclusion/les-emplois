from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.translation import gettext as _

from itou.prescribers.models import PrescriberMembership
from itou.siaes.models import SiaeMembership
from itou.users import models


class SiaeMembershipInline(admin.TabularInline):
    model = SiaeMembership
    extra = 0
    raw_id_fields = ("siae",)
    readonly_fields = ("siae", "siae_id", "joined_at", "is_siae_admin")
    can_delete = False

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request, obj=None):
        return False


class PrescriberMembershipInline(admin.TabularInline):
    model = PrescriberMembership
    extra = 0
    raw_id_fields = ("organization",)
    readonly_fields = ("organization", "organization_id", "joined_at", "is_admin")
    can_delete = False

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request, obj=None):
        return False


class KindFilter(admin.SimpleListFilter):
    title = _("Type")
    parameter_name = "kind"

    def lookups(self, request, model_admin):
        return (
            ("is_job_seeker", _("Demandeur d'emploi")),
            ("is_prescriber", _("Prescripteur")),
            ("is_siae_staff", _("SIAE")),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == "is_job_seeker":
            queryset = queryset.filter(is_job_seeker=True)
        elif value == "is_prescriber":
            queryset = queryset.filter(is_prescriber=True)
        elif value == "is_siae_staff":
            queryset = queryset.filter(is_siae_staff=True)
        return queryset


@admin.register(models.User)
class ItouUserAdmin(UserAdmin):

    list_filter = UserAdmin.list_filter + (KindFilter,)

    list_display = ("id", "email", "first_name", "last_name", "is_staff", "is_created_by_a_proxy", "last_login")

    list_display_links = ("id", "email")

    raw_id_fields = ("created_by",)

    inlines = UserAdmin.inlines + [SiaeMembershipInline, PrescriberMembershipInline]

    fieldsets = UserAdmin.fieldsets + (
        (
            _("Informations"),
            {
                "fields": (
                    "birthdate",
                    "phone",
                    "is_job_seeker",
                    "is_prescriber",
                    "is_siae_staff",
                    "pole_emploi_id",
                    "lack_of_pole_emploi_id_reason",
                    "created_by",
                )
            },
        ),
    )

    def is_created_by_a_proxy(self, obj):
        return obj.created_by is not None

    is_created_by_a_proxy.boolean = True

    def get_queryset(self, request):
        """
        Remove superuser. The purpose is to prevent staff users
        to change the password of a superuser.
        """
        qs = super().get_queryset(request)
        if not request.user.is_superuser:
            qs = qs.exclude(is_superuser=True)
        return qs

    def get_readonly_fields(self, request, obj=None):
        """
        Staff (not superusers) should not manage perms of Users.
        https://code.djangoproject.com/ticket/23559
        """
        rof = super().get_readonly_fields(request, obj)
        if not request.user.is_superuser:
            rof += ("is_staff", "is_superuser", "groups", "user_permissions")
        return rof
