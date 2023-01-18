from allauth.account.admin import EmailAddressAdmin
from allauth.account.models import EmailAddress
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.db.models import Exists, OuterRef
from django.urls import reverse
from django.utils.safestring import mark_safe

from itou.geo.models import QPV
from itou.institutions.models import InstitutionMembership
from itou.prescribers.models import PrescriberMembership
from itou.siaes.models import SiaeMembership
from itou.users import models
from itou.users.admin_forms import UserAdminForm
from itou.utils.admin import PkSupportRemarkInline


class SiaeMembershipInline(admin.TabularInline):
    model = SiaeMembership
    extra = 0
    raw_id_fields = ("siae",)
    readonly_fields = (
        "siae_id_link",
        "joined_at",
        "is_admin",
        "is_active",
        "created_at",
        "updated_at",
        "updated_by",
        "notifications",
    )
    can_delete = True
    show_change_link = True
    fk_name = "user"

    def has_change_permission(self, request, obj=None):
        return True

    def has_add_permission(self, request, obj=None):
        return True

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
        "organization_id_link",
        "joined_at",
        "is_admin",
        "is_active",
        "created_at",
        "updated_at",
        "updated_by",
    )
    can_delete = True
    fk_name = "user"

    def has_change_permission(self, request, obj=None):
        return True

    def has_add_permission(self, request, obj=None):
        return True

    def organization_id_link(self, obj):
        app_label = obj.organization._meta.app_label
        model_name = obj.organization._meta.model_name
        url = reverse(f"admin:{app_label}_{model_name}_change", args=[obj.organization_id])
        return mark_safe(f'<a href="{url}">{obj.organization_id}</a>')


class InstitutionMembershipInline(admin.TabularInline):
    model = InstitutionMembership
    extra = 0
    raw_id_fields = (
        "institution",
        "user",
        "updated_by",
    )
    readonly_fields = (
        "institution_id_link",
        "joined_at",
        "is_admin",
        "is_active",
        "created_at",
        "updated_at",
        "updated_by",
    )
    can_delete = True
    fk_name = "user"

    def has_change_permission(self, request, obj=None):
        return True

    def has_add_permission(self, request, obj=None):
        return True

    def institution_id_link(self, obj):
        app_label = obj.institution._meta.app_label
        model_name = obj.institution._meta.model_name
        url = reverse(f"admin:{app_label}_{model_name}_change", args=[obj.institution_id])
        return mark_safe(f'<a href="{url}">{obj.institution_id}</a>')


class KindFilter(admin.SimpleListFilter):
    title = "Type"
    parameter_name = "kind"

    def lookups(self, request, model_admin):
        return (
            ("is_job_seeker", "Demandeur d'emploi"),
            ("is_prescriber", "Prescripteur"),
            ("is_siae_staff", "SIAE"),
            ("is_labor_inspector", "Inspecteur du travail"),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == "is_job_seeker":
            queryset = queryset.filter(is_job_seeker=True)
        elif value == "is_prescriber":
            queryset = queryset.filter(is_prescriber=True)
        elif value == "is_siae_staff":
            queryset = queryset.filter(is_siae_staff=True)
        elif value == "is_labor_inspector":
            queryset = queryset.filter(is_labor_inspector=True)
        return queryset


class CreatedByProxyFilter(admin.SimpleListFilter):
    title = "Créé par un tiers"
    parameter_name = "created_by"

    def lookups(self, request, model_admin):
        return (("yes", "Oui"), ("no", "Non"))

    def queryset(self, request, queryset):
        value = self.value()
        if value == "yes":
            return queryset.filter(created_by__isnull=False)
        if value == "no":
            return queryset.filter(created_by__isnull=True)
        return queryset


@admin.register(models.User)
class ItouUserAdmin(UserAdmin):

    form = UserAdminForm
    inlines = [
        SiaeMembershipInline,
        PrescriberMembershipInline,
        InstitutionMembershipInline,
        PkSupportRemarkInline,
    ]
    list_display = (
        "pk",
        "email",
        "first_name",
        "last_name",
        "birthdate",
        "is_staff",
        "identity_provider",
        "is_created_by_a_proxy",
        "has_verified_email",
        "last_login",
    )
    list_display_links = ("pk", "email")
    list_filter = UserAdmin.list_filter + (
        KindFilter,
        CreatedByProxyFilter,
        "identity_provider",
    )
    ordering = ("-id",)
    raw_id_fields = (
        "created_by",
        "birth_place",
        "birth_country",
    )
    search_fields = UserAdmin.search_fields + (
        "pk",
        "nir",
        "asp_uid",
    )
    readonly_fields = (
        "pk",
        "asp_uid",
        "jobseeker_hash_id",
        "identity_provider",
        "address_in_qpv",
    )

    fieldsets = UserAdmin.fieldsets + (
        (
            "Informations",
            {
                "fields": (
                    "pk",
                    "asp_uid",
                    "jobseeker_hash_id",
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
                    "address_in_qpv",
                    "is_job_seeker",
                    "is_prescriber",
                    "is_siae_staff",
                    "is_labor_inspector",
                    "nir",
                    "pole_emploi_id",
                    "lack_of_pole_emploi_id_reason",
                    "created_by",
                    "identity_provider",
                )
            },
        ),
    )
    # Add last_checked_at in "Important dates" section, alongside last_login & date_joined
    assert "last_login" in fieldsets[-2][1]["fields"]
    fieldsets[-2][1]["fields"] += ("last_checked_at",)

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
        return bool(obj.created_by_id)

    is_created_by_a_proxy.boolean = True
    is_created_by_a_proxy.short_description = "créé par un tiers"

    @admin.display(description="id ITOU obfusqué")
    def jobseeker_hash_id(self, obj):
        return obj.jobseeker_hash_id

    @admin.display(description="Adresse en QPV")
    def address_in_qpv(self, obj):
        # DO NOT PUT THIS FIELD IN 'list_display' : dynamically computed, only for detail page
        if not obj.coords or obj.geocoding_score < 0.8:
            # Under this geocoding score, we can't assert the quality of this field
            return "Adresse non-géolocalisée"

        if qpv := QPV.in_qpv(obj, geom_field="coords"):
            url = reverse("admin:geo_qpv_change", args=[qpv.pk])
            return mark_safe(f'<a href="{url}">{qpv}</a>')

        return "Adresse hors QPV"

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
            qs = qs.annotate(_has_verified_email=Exists(has_verified_email))
        return qs

    def get_readonly_fields(self, request, obj=None):
        """
        Staff (not superusers) should not manage perms of Users.
        https://code.djangoproject.com/ticket/23559
        """
        rof = super().get_readonly_fields(request, obj)
        if not request.user.is_superuser:
            rof += ("is_staff", "is_superuser", "groups", "user_permissions")
        if obj and obj.has_sso_provider:
            rof += ("first_name", "last_name", "email", "username")
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

    list_display = (
        "pk",
        "user",
        "username",
        "pole_emploi_id",
    )

    search_fields = (
        "user__first_name",
        "user__last_name",
        "user__email",
    )

    readonly_fields = (
        "pole_emploi_id",
        "user",
        "hexa_lane_type",
        "hexa_post_code",
        "hexa_commune",
    )

    fieldsets = (
        (
            "Informations",
            {
                "fields": (
                    "user",
                    "education_level",
                    "pole_emploi_id",
                    "pole_emploi_since",
                    "unemployed_since",
                    "resourceless",
                    "rqth_employee",
                    "oeth_employee",
                )
            },
        ),
        (
            "Aides et prestations sociales",
            {
                "fields": (
                    "has_rsa_allocation",
                    "rsa_allocation_since",
                    "ass_allocation_since",
                    "aah_allocation_since",
                    "ata_allocation_since",
                )
            },
        ),
        (
            "Adresse salarié au format Hexa",
            {
                "fields": (
                    "hexa_lane_number",
                    "hexa_std_extension",
                    "hexa_non_std_extension",
                    "hexa_lane_type",
                    "hexa_lane_name",
                    "hexa_additional_address",
                    "hexa_post_code",
                    "hexa_commune",
                )
            },
        ),
    )

    inlines = (PkSupportRemarkInline,)

    def username(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name}"

    def pole_emploi_id(self, obj):
        return obj.user.pole_emploi_id or "-"

    username.short_description = "Nom complet"
    pole_emploi_id.short_description = "Identifiant Pôle emploi"


class EmailAddressWithRemarkAdmin(EmailAddressAdmin):
    inlines = (PkSupportRemarkInline,)


admin.site.unregister(EmailAddress)
admin.site.register(EmailAddress, EmailAddressWithRemarkAdmin)
