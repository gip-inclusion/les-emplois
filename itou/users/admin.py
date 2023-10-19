from allauth.account.admin import EmailAddressAdmin
from allauth.account.models import EmailAddress
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.db.models import Exists, OuterRef
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html

from itou.approvals.models import Approval
from itou.common_apps.address.models import BAN_API_RELIANCE_SCORE
from itou.eligibility.models import EligibilityDiagnosis, GEIQEligibilityDiagnosis
from itou.geo.models import QPV
from itou.institutions.models import InstitutionMembership
from itou.job_applications.models import JobApplication
from itou.prescribers.models import PrescriberMembership
from itou.siaes.models import SiaeMembership
from itou.users import models
from itou.users.admin_forms import ChooseFieldsToTransfer, ItouUserCreationForm, SelectTargetUserForm, UserAdminForm
from itou.users.enums import IdentityProvider, UserKind
from itou.utils.admin import ItouModelAdmin, ItouTabularInline, PkSupportRemarkInline, get_admin_view_link
from itou.utils.models import PkSupportRemark


class EmailAddressInline(ItouTabularInline):
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


class SiaeMembershipInline(ItouTabularInline):
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


class PrescriberMembershipInline(ItouTabularInline):
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


class InstitutionMembershipInline(ItouTabularInline):
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


class JobApplicationInline(ItouTabularInline):
    model = JobApplication
    fk_name = "job_seeker"
    extra = 0
    can_delete = False
    fields = ("pk_link", "sender_kind", "to_siae_link", "state")
    readonly_fields = fields
    list_select_related = ("to_siae",)

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description="PK")
    def pk_link(self, obj):
        return get_admin_view_link(obj)

    @admin.display(description="SIAE destinataire")
    def to_siae_link(self, obj):
        return format_html(
            "{} — SIRET : {}",
            get_admin_view_link(obj.to_siae, content=obj.to_siae.display_name),
            obj.to_siae.siret,
        )


class SentJobApplicationInline(JobApplicationInline):
    fk_name = "sender"
    fields = ("pk_link", "job_seeker_link", "to_siae_link", "state")
    readonly_fields = fields
    verbose_name = "candidature envoyée"
    verbose_name_plural = "candidatures envoyées"

    @admin.display(description="candidat")
    def job_seeker_link(self, obj):
        return get_admin_view_link(obj.job_seeker, content=obj.job_seeker.get_full_name())


class EligibilityDiagnosisInline(ItouTabularInline):
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

    @admin.display(boolean=True, description="en cours de validité")
    def is_valid(self, obj):
        return obj.is_valid


class GEIQEligibilityDiagnosisInline(EligibilityDiagnosisInline):
    model = GEIQEligibilityDiagnosis


class ApprovalInline(ItouTabularInline):
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

    @admin.display(description="numéro")
    def pk_link(self, obj):
        return get_admin_view_link(obj, content=obj.number)

    @admin.display(boolean=True, description="en cours de validité")
    def is_valid(self, obj):
        return obj.is_valid()


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


JOB_SEEKER_FIELDS_TO_TRANSFER = {
    "approvals",  # Approval.user
    "eligibility_diagnoses",  # EligibilityDiagnosis.job_seeker
    "geiq_eligibility_diagnoses",  # GEIQEligibilityDiagnosis.job_seeker
    "job_applications",  # JobApplication.job_seeker
}


def get_fields_to_transfer_for_job_seekers():
    # Get list of fields pointing to the User models
    return {models.User._meta.get_field(name) for name in JOB_SEEKER_FIELDS_TO_TRANSFER}


def add_support_remark_to_user(user, text):
    user_content_type = ContentType.objects.get_for_model(models.User)
    try:
        remark = PkSupportRemark.objects.filter(content_type=user_content_type, object_id=user.pk).get()
    except PkSupportRemark.DoesNotExist:
        PkSupportRemark.objects.create(content_type=user_content_type, object_id=user.pk, remark=text)
    else:
        remark.remark += "\n" + text
        remark.save(update_fields=("remark",))


@admin.register(models.User)
class ItouUserAdmin(UserAdmin):
    show_full_result_count = False
    add_form = ItouUserCreationForm
    change_form_template = "admin/users/change_user_form.html"
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
    raw_id_fields = ("created_by",)
    readonly_fields = (
        "pk",
        "identity_provider",
        "address_in_qpv",
        "is_staff",
        "jobseeker_profile_link",
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
                    "jobseeker_profile_link",
                )
            },
        ),
    )
    # Add last_checked_at in "Important dates" section, alongside last_login & date_joined
    assert "last_login" in fieldsets[-2][1]["fields"]
    fieldsets[-2][1]["fields"] += ("last_checked_at",)

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "username",
                    "email",
                ),
            },
        ),
        (
            "Type d’utilisateur",
            {
                "classes": ["wide"],
                "fields": ["kind"],
            },
        ),
    )

    @admin.display(boolean=True, description="email validé", ordering="_has_verified_email")
    def has_verified_email(self, obj):
        """
        Quickly identify unverified email that could be the result of a typo.
        """
        return obj._has_verified_email

    @admin.display(boolean=True, description="créé par un tiers")
    def is_created_by_a_proxy(self, obj):
        # Use the "hidden" field with an `_id` suffix to avoid hitting the database for each row.
        # https://docs.djangoproject.com/en/dev/ref/models/fields/#database-representation
        return bool(obj.created_by_id)

    @admin.display(description="adresse en QPV")
    def address_in_qpv(self, obj):
        # DO NOT PUT THIS FIELD IN 'list_display' : dynamically computed, only for detail page
        if not obj.coords:
            return "Adresse non-géolocalisée"
        elif obj.geocoding_score < BAN_API_RELIANCE_SCORE:
            return "Adresse imprécise"

        if qpv := QPV.in_qpv(obj, geom_field="coords"):
            return get_admin_view_link(qpv, content=qpv)

        return "Adresse hors QPV"

    @admin.display(description="profil de demandeur d'emploi")
    def jobseeker_profile_link(self, obj):
        return get_admin_view_link(obj.jobseeker_profile) if obj.is_job_seeker else None

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
        if obj:
            rof += ("kind",)  # kind is never editable, but still addable
        return rof

    def get_search_fields(self, request):
        search_fields = []
        search_term = request.GET.get("q", "").strip()
        if len(search_term) == 30:
            try:
                int(search_term, base=16)
            except ValueError:
                pass
            else:
                search_fields.append("asp_uid__exact")
        if search_term.isdecimal():
            search_fields.append("pk__exact")
            search_fields.append("nir__exact")
        else:
            search_fields.append("email")
            if "@" not in search_term:
                search_fields.append("first_name")
                search_fields.append("last_name")
        return search_fields

    def get_inlines(self, request, obj):
        inlines = [PkSupportRemarkInline]
        if not obj:
            return tuple(inlines)
        inlines.insert(0, EmailAddressInline)

        conditional_inlines = {
            "is_employer": {
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

    def get_urls(self):
        urls = super().get_urls()
        return [
            path(
                "transfer/<int:from_user_pk>",
                self.admin_site.admin_view(self.transfer_view),
                name="transfer_user_data",
            ),
            path(
                "transfer/<int:from_user_pk>/<int:to_user_pk>",
                self.admin_site.admin_view(self.transfer_view),
                name="transfer_user_data",
            ),
        ] + urls

    def transfer_view(self, request, from_user_pk, to_user_pk=None):
        if not self.has_change_permission(request):
            raise PermissionDenied

        from_user = get_object_or_404(models.User.objects.filter(kind=UserKind.JOB_SEEKER), pk=from_user_pk)
        to_user = (
            get_object_or_404(models.User.objects.filter(kind=UserKind.JOB_SEEKER), pk=to_user_pk)
            if to_user_pk is not None
            else None
        )

        def _get_transfer_data_from_user(user, field):
            data = []
            for item in getattr(user, field.name).all():
                item.admin_link = reverse(
                    f"admin:{item._meta.app_label}_{item._meta.model_name}_change", args=[item.pk]
                )
                data.append(item)
            return data

        transfer_fields = {field.name: field for field in get_fields_to_transfer_for_job_seekers()}
        fields_choices = []
        transfer_data = {}
        for field in transfer_fields.values():
            title = field.related_model._meta.verbose_name_plural.upper()
            from_data = _get_transfer_data_from_user(from_user, field)
            to_data = _get_transfer_data_from_user(to_user, field) if to_user else None
            transfer_data[field.name] = {
                "title": title,
                "from": from_data,
                "to": to_data,
            }
            plural = "s" if len(from_data) > 1 else ""
            if from_data:
                fields_choices.append((field.name, f"{title} ({len(from_data)} objet{plural} à transférer)"))

        if not to_user:
            form = SelectTargetUserForm(
                from_user=from_user,
                admin_site=self.admin_site,
                data=request.POST or None,
            )
            if request.POST and form.is_valid():
                return redirect(
                    reverse(
                        "admin:transfer_user_data",
                        kwargs={"from_user_pk": from_user.pk, "to_user_pk": form.cleaned_data["to_user"].pk},
                    )
                )
        else:
            form = ChooseFieldsToTransfer(
                fields_choices=sorted(fields_choices, key=lambda field: field[1]), data=request.POST or None
            )
            if request.POST and form.is_valid():
                items_transfered = []
                for field_name in form.cleaned_data["fields_to_transfer"]:
                    field = transfer_fields[field_name]
                    for item in transfer_data[field_name]["from"]:
                        setattr(item, field.remote_field.name, to_user)
                        item.save()
                        items_transfered.append((transfer_data[field_name]["title"], item))
                if items_transfered:
                    summary_text = "\n".join(
                        [
                            "-" * 20,
                            f"Transfert du {timezone.now():%Y-%m-%d %H:%M:%S} effectué par {request.user} ",
                            f"de l'utilisateur {from_user.pk} vers {to_user.pk}:",
                        ]
                        + [f"- {item_title} {item} transféré " for item_title, item in items_transfered]
                        + ["-" * 20]
                    )
                    add_support_remark_to_user(from_user, summary_text)
                    add_support_remark_to_user(to_user, summary_text)
                    message = format_html(
                        "Transfert effectué avec succès de l'utilisateur {from_user} vers {to_user}.",
                        from_user=from_user,
                        to_user=to_user,
                    )
                    messages.info(request, message)

                return redirect(
                    reverse(
                        "admin:users_user_change",
                        kwargs={"object_id": to_user.pk},
                    )
                )
        title = f"Transfert des données de { from_user }"
        if to_user:
            title += f" vers { to_user}"
        context = self.admin_site.each_context(request) | {
            "media": self.media,
            "opts": self.opts,
            "form": form,
            "from_user": from_user,
            "to_user": to_user,
            "nothing_to_transfer": not fields_choices,
            "transfer_data": sorted(transfer_data.values(), key=lambda data: data["title"]),
            "title": title,
        }

        return TemplateResponse(
            request,
            "admin/users/transfer_user.html",
            context,
        )


class IsPECertifiedFilter(admin.SimpleListFilter):
    title = "Certifié par Pôle Emploi"
    parameter_name = "is_pe_certified"

    def lookups(self, request, model_admin):
        return (("yes", "Oui"), ("no", "Non"))

    def queryset(self, request, queryset):
        value = self.value()
        if value == "yes":
            return queryset.exclude(pe_obfuscated_nir=None)
        if value == "no":
            return queryset.filter(pe_obfuscated_nir=None)
        return queryset


@admin.register(models.JobSeekerProfile)
class JobSeekerProfileAdmin(ItouModelAdmin):
    """
    Inlines would only be possible the other way around
    """

    raw_id_fields = (
        "user",
        "birth_place",
        "birth_country",
        "hexa_commune",
    )

    list_display = (
        "pk",
        "user_link",
        "username",
        "birthdate",
        "nir",
        "pole_emploi_id",
        "is_pe_certified",
    )

    list_filter = (IsPECertifiedFilter,)

    list_select_related = ("user",)

    search_fields = (
        "user__first_name",
        "user__last_name",
        "user__email",
    )

    readonly_fields = (
        "nir",
        "pole_emploi_id",
        "hexa_lane_type",
        "hexa_post_code",
        "hexa_commune",
        "pe_obfuscated_nir",
        "pe_last_certification_attempt_at",
        "is_pe_certified",
    )

    fieldsets = (
        (
            "Informations",
            {
                "fields": (
                    "user",
                    "birth_place",
                    "birth_country",
                    "education_level",
                    "nir",
                    "pole_emploi_id",
                    "pole_emploi_since",
                    "unemployed_since",
                    "resourceless",
                    "rqth_employee",
                    "oeth_employee",
                    "is_pe_certified",
                    "pe_obfuscated_nir",
                    "pe_last_certification_attempt_at",
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

    @admin.display(description="date de naissance")
    def birthdate(self, obj):
        return obj.user.birthdate

    @admin.display(description="NIR")
    def nir(self, obj):
        return obj.user.nir or "-"

    @admin.display(description="nom complet")
    def username(self, obj):
        return obj.user.get_full_name()

    @admin.display(description="identifiant Pôle emploi")
    def pole_emploi_id(self, obj):
        return obj.user.pole_emploi_id or "-"

    @admin.display(boolean=True, description="profil certifié par Pôle emploi")
    def is_pe_certified(self, obj):
        return obj.pe_obfuscated_nir is not None

    @admin.display(description="utilisateur")
    def user_link(self, obj):
        return get_admin_view_link(obj.user, content=f"🔗 {obj.user.email}")


class EmailAddressWithRemarkAdmin(EmailAddressAdmin):
    inlines = (PkSupportRemarkInline,)


admin.site.unregister(EmailAddress)
admin.site.register(EmailAddress, EmailAddressWithRemarkAdmin)
