from allauth.account.admin import EmailAddressAdmin
from allauth.account.models import EmailAddress
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.db.models import Exists, OuterRef
from django.utils.safestring import mark_safe

from itou.approvals.models import Approval
from itou.eligibility.models import EligibilityDiagnosis, GEIQEligibilityDiagnosis
from itou.geo.models import QPV
from itou.institutions.models import InstitutionMembership
from itou.job_applications.models import JobApplication
from itou.prescribers.models import PrescriberMembership
from itou.siaes.models import SiaeMembership
from itou.users import models
from itou.users.admin_forms import ItouUserCreationForm, UserAdminForm
from itou.users.enums import IdentityProvider
from itou.utils.admin import PkSupportRemarkInline, get_admin_view_link


class EmailAddressInline(admin.TabularInline):
    model = EmailAddress
    extra = 0
    can_delete = False
    fields = ("pk_link", "verified", "primary")
    readonly_fields = fields

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description="PK")
    def pk_link(self, obj):
        return get_admin_view_link(obj, content=obj.email)


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
        return get_admin_view_link(obj.siae)


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
        return get_admin_view_link(obj.organization)


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
        return get_admin_view_link(obj.institution)


class JobApplicationInline(admin.TabularInline):
    model = JobApplication
    fk_name = "job_seeker"
    extra = 0
    can_delete = False
    fields = ("pk_link", "sender_kind", "to_siae_link", "state")
    readonly_fields = fields

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description="PK")
    def pk_link(self, obj):
        return get_admin_view_link(obj)

    @admin.display(description="SIAE destinataire")
    def to_siae_link(self, obj):
        return mark_safe(
            get_admin_view_link(obj.to_siae, content=obj.to_siae.display_name) + f" — SIRET : {obj.to_siae.siret}"
        )


class SentJobApplicationInline(JobApplicationInline):
    fk_name = "sender"
    fields = ("pk_link", "job_seeker_link", "to_siae_link", "state")
    readonly_fields = fields
    verbose_name = "Candidature envoyée"
    verbose_name_plural = "Candidatures envoyées"

    @admin.display(description="Candidat")
    def job_seeker_link(self, obj):
        return get_admin_view_link(obj.job_seeker, content=obj.job_seeker.get_full_name())


class EligibilityDiagnosisInline(admin.TabularInline):
    model = EligibilityDiagnosis
    fk_name = "job_seeker"
    extra = 0
    can_delete = False
    fields = (
        "pk_link",
        "author",
        "author_kind",
        "is_valid",
    )
    readonly_fields = fields

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description="PK")
    def pk_link(self, obj):
        return get_admin_view_link(obj)

    def is_valid(self, obj):
        return obj.is_valid

    is_valid.boolean = True
    is_valid.short_description = "En cours de validité"


class GEIQEligibilityDiagnosisInline(EligibilityDiagnosisInline):
    model = GEIQEligibilityDiagnosis


class ApprovalInline(admin.TabularInline):
    model = Approval
    fk_name = "user"
    extra = 0
    can_delete = False
    fields = (
        "pk_link",
        "start_at",
        "end_at",
        "is_valid",
    )
    readonly_fields = fields

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description="Numéro")
    def pk_link(self, obj):
        return get_admin_view_link(obj, content=obj.number)

    def is_valid(self, obj):
        return obj.is_valid()

    is_valid.boolean = True
    is_valid.short_description = "En cours de validité"


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

    add_form = ItouUserCreationForm
    form = UserAdminForm
    list_display = (
        "pk",
        "email",
        "first_name",
        "last_name",
        "birthdate",
        "kind",
        "identity_provider",
        "is_created_by_a_proxy",
        "has_verified_email",
        "last_login",
    )
    list_display_links = ("pk", "email")
    list_filter = UserAdmin.list_filter + (
        "kind",
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
        "identity_provider",
        "address_in_qpv",
        "is_staff",
    )

    fieldsets = UserAdmin.fieldsets + (
        (
            "Informations",
            {
                "fields": (
                    "pk",
                    "asp_uid",
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
                    "kind",
                    "nir",
                    "lack_of_nir_reason",
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

    add_fieldsets = UserAdmin.add_fieldsets + (
        (
            "Type d’utilisateur",
            {
                "classes": ["wide"],
                "fields": ["kind"],
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
        return bool(obj.created_by_id)

    is_created_by_a_proxy.boolean = True
    is_created_by_a_proxy.short_description = "créé par un tiers"

    @admin.display(description="Adresse en QPV")
    def address_in_qpv(self, obj):
        # DO NOT PUT THIS FIELD IN 'list_display' : dynamically computed, only for detail page
        if not obj.coords or obj.geocoding_score < 0.8:
            # Under this geocoding score, we can't assert the quality of this field
            return "Adresse non-géolocalisée"

        if qpv := QPV.in_qpv(obj, geom_field="coords"):
            return get_admin_view_link(qpv, content=qpv)

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
            rof += ("username",)
            if obj.identity_provider != IdentityProvider.PE_CONNECT:
                rof += ("first_name", "last_name", "email")
        return rof

    def get_inlines(self, request, obj):
        inlines = [PkSupportRemarkInline]
        if not obj:
            return tuple(inlines)
        inlines.insert(0, EmailAddressInline)

        conditional_inlines = {
            "is_siae_staff": {
                "siaemembership_set": SiaeMembershipInline,
                "job_applications_sent": SentJobApplicationInline,
            },
            "is_prescriber": {
                "prescribermembership_set": PrescriberMembershipInline,
                "job_applications_sent": SentJobApplicationInline,
            },
            "is_labor_inspector": {"institutionmembership_set": InstitutionMembershipInline},
            "is_job_seeker": {
                "eligibility_diagnoses": EligibilityDiagnosisInline,
                "geiq_eligibility_diagnoses": GEIQEligibilityDiagnosisInline,
                "approvals": ApprovalInline,
                "job_applications": JobApplicationInline,
            },
        }
        strict_fields = {"job_applications", "job_applications_sent"}
        for check, related_fields in conditional_inlines.items():
            for field_name, inline_class in related_fields.items():
                is_strict = field_name in strict_fields
                if getattr(obj, check) or (not is_strict and getattr(obj, field_name).all()):
                    inlines.insert(-1, inline_class)

        return tuple(inlines)


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
