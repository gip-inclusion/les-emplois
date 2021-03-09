from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.db.models import Exists, OuterRef
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _

from itou.prescribers.models import PrescriberMembership
from itou.siaes.models import SiaeMembership
from itou.users import models


class SiaeMembershipInline(admin.TabularInline):
    model = SiaeMembership
    extra = 0
    raw_id_fields = ("siae",)
    readonly_fields = (
        "siae",
        "siae_id_link",
        "joined_at",
        "is_siae_admin",
        "is_active",
        "created_at",
        "updated_at",
        "updated_by",
    )
    can_delete = False
    show_change_link = True
    fk_name = "user"

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request, obj=None):
        return False

    def siae_id_link(self, obj):
        app_label = obj.siae._meta.app_label
        model_name = obj.siae._meta.model_name
        url = reverse(f"admin:{app_label}_{model_name}_change", args=[obj.siae_id])
        return mark_safe(f'<a href="{url}">{obj.siae_id}</a>')


class PrescriberMembershipInline(admin.TabularInline):
    model = PrescriberMembership
    extra = 0
    raw_id_fields = ("organization",)
    readonly_fields = (
        "organization",
        "organization_id_link",
        "joined_at",
        "is_admin",
        "is_active",
        "created_at",
        "updated_at",
        "updated_by",
    )
    can_delete = False
    fk_name = "user"

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request, obj=None):
        return False

    def organization_id_link(self, obj):
        app_label = obj.organization._meta.app_label
        model_name = obj.organization._meta.model_name
        url = reverse(f"admin:{app_label}_{model_name}_change", args=[obj.organization_id])
        return mark_safe(f'<a href="{url}">{obj.organization_id}</a>')


class KindFilter(admin.SimpleListFilter):
    title = _("Type")
    parameter_name = "kind"

    def lookups(self, request, model_admin):
        return (
            ("is_job_seeker", _("Demandeur d'emploi")),
            ("is_prescriber", _("Prescripteur")),
            ("is_siae_staff", _("SIAE")),
            ("is_stats_vip", _("Pilotage")),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == "is_job_seeker":
            queryset = queryset.filter(is_job_seeker=True)
        elif value == "is_prescriber":
            queryset = queryset.filter(is_prescriber=True)
        elif value == "is_siae_staff":
            queryset = queryset.filter(is_siae_staff=True)
        elif value == "is_stats_vip":
            queryset = queryset.filter(is_stats_vip=True)
        return queryset


class CreatedByProxyFilter(admin.SimpleListFilter):
    title = _("Créé par un tiers")
    parameter_name = "created_by"

    def lookups(self, request, model_admin):
        return (("yes", _("Oui")), ("no", _("Non")))

    def queryset(self, request, queryset):
        value = self.value()
        if value == "yes":
            return queryset.filter(created_by__isnull=False)
        if value == "no":
            return queryset.filter(created_by__isnull=True)
        return queryset


@admin.register(models.User)
class ItouUserAdmin(UserAdmin):

    inlines = UserAdmin.inlines + [
        SiaeMembershipInline,
        PrescriberMembershipInline,
    ]
    list_display = (
        "pk",
        "email",
        "first_name",
        "last_name",
        "is_staff",
        "is_peamu",
        "is_created_by_a_proxy",
        "has_verified_email",
        "last_login",
    )
    list_display_links = ("pk", "email")
    list_filter = UserAdmin.list_filter + (KindFilter, CreatedByProxyFilter)
    ordering = ("-id",)
    raw_id_fields = (
        "created_by",
        "birth_place",
        "birth_country",
    )
    search_fields = UserAdmin.search_fields + ("pk",)
    readonly_fields = ("pk",)

    fieldsets = UserAdmin.fieldsets + (
        (
            _("Informations"),
            {
                "fields": (
                    "pk",
                    "title",
                    "birthdate",
                    "birth_place",
                    "birth_country",
                    "phone",
                    "resume_link",
                    "address_line_1",
                    "address_line_2",
                    "post_code",
                    "department",
                    "city",
                    "is_job_seeker",
                    "is_prescriber",
                    "is_siae_staff",
                    "is_stats_vip",
                    "pole_emploi_id",
                    "lack_of_pole_emploi_id_reason",
                    "created_by",
                )
            },
        ),
    )

    def has_verified_email(self, obj):
        """
        Quickly identify unverified email that could be the result of a typo.
        """
        return obj._has_verified_email

    has_verified_email.boolean = True
    has_verified_email.admin_order_field = "_has_verified_email"
    has_verified_email.short_description = "Email validé"

    def is_created_by_a_proxy(self, obj):
        # Use the "hidden" field with an `_id` suffix to avoid hitting the database for each row.
        # https://docs.djangoproject.com/en/dev/ref/models/fields/#database-representation
        return bool(obj.created_by)

    is_created_by_a_proxy.boolean = True
    is_created_by_a_proxy.short_description = "créé par un tiers"

    def is_peamu(self, obj):
        return obj._is_peamu

    is_peamu.boolean = True
    is_peamu.admin_order_field = "_is_peamu"
    is_peamu.short_description = "pe connect"

    def get_queryset(self, request):
        """
        Exclude superusers. The purpose is to prevent staff users
        to change the password of a superuser.
        """
        qs = super().get_queryset(request)
        if not request.user.is_superuser:
            qs = qs.exclude(is_superuser=True)
        if request.resolver_match.view_name.endswith("changelist"):
            has_verified_email = EmailAddress.objects.filter(email=OuterRef("email"), verified=True)
            is_peamu = SocialAccount.objects.filter(user_id=OuterRef("pk"), provider="peamu")
            qs = qs.annotate(_has_verified_email=Exists(has_verified_email))
            qs = qs.annotate(_is_peamu=Exists(is_peamu))
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


@admin.register(models.JobSeekerProfile)
class JobSeekerProfileAdmin(admin.ModelAdmin):
    """
    Inlines would only be possible the other way around
    """

    raw_id_fields = (
        "user",
        "hexa_commune",
    )
    list_display = ("pk", "user", "username")

    fieldsets = (
        (
            _("Informations"),
            {"fields": ("user", "education_level")},
        ),
        (
            _("Aides et prestations sociales"),
            {
                "fields": (
                    "resourceless",
                    "rqth_employee",
                    "oeth_employee",
                    "pole_emploi_since",
                    "unemployed_since",
                    "rsa_allocation_since",
                    "ass_allocation_since",
                    "aah_allocation_since",
                    "ata_allocation_since",
                )
            },
        ),
        (
            _("Adresse salarié au format Hexa"),
            {
                "fields": (
                    "hexa_lane_number",
                    "hexa_std_extension",
                    "hexa_non_std_extension",
                    "hexa_lane_type",
                    "hexa_lane_name",
                    "hexa_post_code",
                    "hexa_commune",
                )
            },
        ),
    )

    def username(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name}"

    username.short_description = _("Nom complet")
