import uuid
from pprint import pformat

from allauth.account.admin import EmailAddressAdmin
from allauth.account.models import EmailAddress
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.core.exceptions import PermissionDenied
from django.db.models import Exists, OuterRef
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from itou.approvals.models import Approval
from itou.common_apps.address.models import BAN_API_RELIANCE_SCORE
from itou.communications.models import NotificationSettings
from itou.companies.models import CompanyMembership
from itou.eligibility.models import EligibilityDiagnosis, GEIQEligibilityDiagnosis
from itou.geo.models import QPV
from itou.gps.models import FollowUpGroupMembership
from itou.institutions.models import InstitutionMembership
from itou.job_applications.models import JobApplication
from itou.prescribers.models import PrescriberMembership
from itou.users import models
from itou.users.admin_forms import (
    ItouUserCreationForm,
    JobSeekerProfileAdminForm,
    SelectTargetUserForm,
    UserAdminForm,
)
from itou.users.enums import IdentityCertificationAuthorities, IdentityProvider, UserKind
from itou.utils.admin import (
    ChooseFieldsToTransfer,
    CreatedOrUpdatedByMixin,
    InconsistencyCheckMixin,
    ItouModelAdmin,
    ItouTabularInline,
    PkSupportRemarkInline,
    ReadonlyMixin,
    add_support_remark_to_obj,
    get_admin_view_link,
    get_structure_view_link,
)
from itou.utils.urls import add_url_params


class EmailAddressInline(ReadonlyMixin, ItouTabularInline):
    model = EmailAddress
    extra = 0
    fields = ("pk_link", "verified", "primary")
    readonly_fields = fields

    @admin.display(description="PK")
    def pk_link(self, obj):
        return get_admin_view_link(obj, content=obj.email)


class DisabledNotificationsMixin:
    @admin.display(description="Notifications désactivées")
    def disabled_notifications(self, obj):
        if obj.user.is_employer:
            notification_settings, _ = NotificationSettings.get_or_create(obj.user, obj.company)
        elif obj.user.is_prescriber:
            notification_settings, _ = NotificationSettings.get_or_create(obj.user, obj.organization)
        else:
            notification_settings, _ = NotificationSettings.get_or_create(obj.user)

        disabled_notifications = notification_settings.disabled_notifications_names
        if disabled_notifications:
            return mark_safe(
                "<ul class='inline'>"
                + "".join([f"<li>{notification}</<li>" for notification in disabled_notifications])
                + "<ul>"
            )
        return "Aucune"


class CompanyMembershipInline(ReadonlyMixin, DisabledNotificationsMixin, ItouTabularInline):
    model = CompanyMembership
    extra = 0
    readonly_fields = (
        "company_siret_link",
        "joined_at",
        "is_admin",
        "is_active",
        "disabled_notifications",
        "created_at",
        "updated_at",
        "updated_by",
    )
    fields = readonly_fields
    show_change_link = True
    fk_name = "user"

    @admin.display(description="Entreprise")
    def company_siret_link(self, obj):
        return get_structure_view_link(obj.company)


class PrescriberMembershipInline(ReadonlyMixin, DisabledNotificationsMixin, ItouTabularInline):
    model = PrescriberMembership
    extra = 0
    readonly_fields = (
        "organization_id_link",
        "joined_at",
        "is_admin",
        "is_active",
        "disabled_notifications",
        "created_at",
        "updated_at",
        "updated_by",
    )
    fields = readonly_fields
    fk_name = "user"

    def organization_id_link(self, obj):
        return get_structure_view_link(obj.organization)


class InstitutionMembershipInline(ReadonlyMixin, ItouTabularInline):
    model = InstitutionMembership
    extra = 0
    readonly_fields = (
        "institution_id_link",
        "joined_at",
        "is_admin",
        "is_active",
        "created_at",
        "updated_at",
        "updated_by",
    )
    fields = readonly_fields
    fk_name = "user"

    def institution_id_link(self, obj):
        return get_structure_view_link(obj.institution)


class JobApplicationInline(ReadonlyMixin, ItouTabularInline):
    model = JobApplication
    fk_name = "job_seeker"
    extra = 0
    fields = ("pk_link", "created_at", "sender_kind", "to_company_link", "state")
    readonly_fields = fields
    list_select_related = ("to_company", "job_seeker")

    @admin.display(description="PK")
    def pk_link(self, obj):
        return get_admin_view_link(obj)

    @admin.display(description="Entreprise destinataire")
    def to_company_link(self, obj):
        return format_html(
            "{} — SIRET : {}",
            get_admin_view_link(obj.to_company, content=obj.to_company.display_name),
            obj.to_company.siret,
        )


class SentJobApplicationInline(JobApplicationInline):
    fk_name = "sender"
    fields = ("pk_link", "created_at", "job_seeker_link", "to_company_link", "state")
    readonly_fields = fields
    verbose_name = "candidature envoyée"
    verbose_name_plural = "candidatures envoyées"

    @admin.display(description="candidat")
    def job_seeker_link(self, obj):
        return get_admin_view_link(obj.job_seeker, content=obj.job_seeker.get_full_name())


class EligibilityDiagnosisInline(ReadonlyMixin, ItouTabularInline):
    model = EligibilityDiagnosis
    fk_name = "job_seeker"
    extra = 0
    fields = (
        "pk_link",
        "author",
        "author_kind",
        "is_valid",
    )
    readonly_fields = fields

    @admin.display(description="PK")
    def pk_link(self, obj):
        return get_admin_view_link(obj)

    @admin.display(boolean=True, description="en cours de validité")
    def is_valid(self, obj):
        if obj.pk:
            return obj.is_valid
        return None


class GEIQEligibilityDiagnosisInline(EligibilityDiagnosisInline):
    model = GEIQEligibilityDiagnosis


class ApprovalInline(ReadonlyMixin, ItouTabularInline):
    model = Approval
    fk_name = "user"
    extra = 0
    fields = (
        "pk_link",
        "start_at",
        "end_at",
        "is_valid",
    )
    readonly_fields = fields

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


@admin.register(models.User)
class ItouUserAdmin(InconsistencyCheckMixin, CreatedOrUpdatedByMixin, UserAdmin):
    class Media:
        css = {"all": ("css/itou-admin.css",)}

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
        "public_id",
        "identity_provider",
        "address_in_qpv",
        "birthdate",
        "is_staff",
        "jobseeker_profile_link",
        "disabled_notifications",
        "follow_up_groups_or_members",
    )

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

    INCONSISTENCY_CHECKS = [
        (
            "Candidature liée au PASS IAE d'un autre candidat",
            lambda q: JobApplication.objects.filter(job_seeker__in=q).inconsistent_approval_user(),
        ),
        (
            "Candidature liée au diagnostic d'un autre candidat",
            lambda q: JobApplication.objects.filter(job_seeker__in=q).inconsistent_eligibility_diagnosis_job_seeker(),
        ),
        (
            "Candidature liée au diagnostic GEIQ d'un autre candidat",
            lambda q: JobApplication.objects.filter(
                job_seeker__in=q
            ).inconsistent_geiq_eligibility_diagnosis_job_seeker(),
        ),
        (
            "PASS IAE lié au diagnostic d'un autre candidat",
            lambda q: Approval.objects.filter(user__in=q).inconsistent_eligibility_diagnosis_job_seeker(),
        ),
    ]

    @admin.display(description="date de naissance")
    def birthdate(self, obj):
        return obj.jobseeker_profile.birthdate if obj.is_job_seeker else None

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
        if not obj.coords or not obj.geocoding_score:
            return "Adresse non-géolocalisée"
        elif obj.geocoding_score < BAN_API_RELIANCE_SCORE:
            return "Adresse imprécise"

        if qpv := QPV.in_qpv(obj, geom_field="coords"):
            return get_admin_view_link(qpv, content=qpv)

        return "Adresse hors QPV"

    @admin.display(description="profil de demandeur d'emploi")
    def jobseeker_profile_link(self, obj):
        return get_admin_view_link(obj.jobseeker_profile) if obj.is_job_seeker else None

    @admin.display(description="Notifications désactivées")
    def disabled_notifications(self, obj):
        if obj.is_employer:
            return "Voir pour chaque structure ci-dessous"
        if obj.is_prescriber:
            return "Voir pour chaque organisation ci-dessous"
        notification_settings, _ = NotificationSettings.get_or_create(obj)
        disabled_notifications = notification_settings.disabled_notifications_names
        if disabled_notifications:
            return mark_safe(
                "<ul class='inline'>"
                + "".join([f"<li>{notification}</<li>" for notification in disabled_notifications])
                + "<ul>"
            )
        return "Aucune"

    @admin.display(description="GPS")
    def follow_up_groups_or_members(self, obj):
        if obj.pk is None:
            return self.get_empty_value_display()
        if obj.is_job_seeker:
            if memberships := FollowUpGroupMembership.objects.filter(follow_up_group__beneficiary=obj):
                url = reverse("admin:gps_followupgroup_change", args=(memberships[0].follow_up_group_id,))
                return format_html('<a href="{}">Groupe de suivi de ce bénéficiaire</a>', url, len(memberships))
            return "Pas de groupe de suivi"
        if obj.is_prescriber or obj.is_employer:
            url = add_url_params(reverse("admin:gps_followupgroupmembership_changelist"), {"member": obj.id})
            count = FollowUpGroupMembership.objects.filter(member=obj).count()
            return format_html('<a href="{}">Liste des relations de cet utilisateur ({}) </a>', url, count)
        return ""

    @admin.action(description="Désactiver le compte IC / PC pour changement prescripteur <-> employeur")
    def free_sso_email(self, request, queryset):
        try:
            [user] = queryset
        except ValueError:
            messages.error(request, "Vous ne pouvez selectionner qu'un seul utilisateur à la fois")
            return

        if user.identity_provider not in [IdentityProvider.INCLUSION_CONNECT, IdentityProvider.PRO_CONNECT]:
            messages.error(request, "Vous devez sélectionner un compte Inclusion Connect ou ProConnect")
            return

        if user.username.startswith("old"):
            messages.error(request, "Ce compte a déjà été libéré")
            return

        user.email = f"{user.email}_old"
        user.username = f"old_{user.username}"
        user.is_active = False
        user.save(update_fields=("email", "username", "is_active"))
        user.prescribermembership_set.update(is_active=False)
        user.companymembership_set.update(is_active=False)

        messages.success(request, "L'utilisateur peut à présent se créer un nouveau compte")

    actions = [free_sso_email]

    def get_queryset(self, request):
        """
        Exclude superusers. The purpose is to prevent staff users
        to change the password of a superuser.
        """
        qs = super().get_queryset(request).select_related("jobseeker_profile")
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

    def get_fieldsets(self, request, obj=None):
        fieldsets = super().get_fieldsets(request, obj=obj)
        if obj is None:
            # add_fieldsets
            return fieldsets

        fieldsets = list(fieldsets)
        fieldsets.append(
            (
                "Informations",
                {
                    "fields": (
                        "pk",
                        "title",
                        "phone",
                        "address_line_1",
                        "address_line_2",
                        "post_code",
                        "department",
                        "city",
                        "address_in_qpv",
                        "kind",
                        "created_by",
                        "identity_provider",
                        "jobseeker_profile_link",
                        "disabled_notifications",
                        "follow_up_groups_or_members",
                    )
                },
            ),
        )

        assert fieldsets[0] == (None, {"fields": ("username", "password")})
        fieldsets[0] = (None, {"fields": ("username", "public_id", "password")})

        # Add last_checked_at in "Important dates" section, alongside last_login & date_joined
        assert "last_login" in fieldsets[-2][1]["fields"]
        fieldsets[-2] = ("Dates importantes", {"fields": ("last_login", "date_joined", "last_checked_at")})

        assert fieldsets[2][0] == "Permissions"
        if request.user.is_superuser:
            # Hide space-consuming widgets for groups and user_permissions.
            if not obj.is_staff:
                fieldsets[2] = ("Permissions", {"fields": ["is_active", "is_staff", "is_superuser"]})
        else:
            fieldsets[2] = ("Permissions", {"fields": ["is_active"]})

        return fieldsets

    def get_search_fields(self, request):
        search_fields = []
        search_term = request.GET.get("q", "").strip()
        if len(search_term) == 30:
            try:
                int(search_term, base=16)
            except ValueError:
                pass
            else:
                search_fields.append("jobseeker_profile__asp_uid__exact")
        try:
            uuid.UUID(search_term)
            search_fields.append("public_id__exact")
        except ValueError:
            pass
        if search_term.isdecimal():
            search_fields.append("pk__exact")
            search_fields.append("jobseeker_profile__nir__exact")
        else:
            search_fields.append("email")
            if "@" not in search_term:
                search_fields.append("first_name__unaccent")
                search_fields.append("last_name__unaccent")
        return search_fields

    def get_inlines(self, request, obj):
        inlines = [PkSupportRemarkInline]
        if not obj:
            return tuple(inlines)
        inlines.insert(0, EmailAddressInline)

        conditional_inlines = {
            "is_employer": {
                "companymembership_set": CompanyMembershipInline,
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
                    add_support_remark_to_obj(from_user, summary_text)
                    add_support_remark_to_obj(to_user, summary_text)
                    message = format_html(
                        "Transfert effectué avec succès de l'utilisateur {from_user} vers {to_user}.",
                        from_user=from_user,
                        to_user=to_user,
                    )
                    messages.info(request, message)

                self.check_inconsistencies(request, models.User.objects.filter(pk__in=(from_user.pk, to_user.pk)))
                return redirect(
                    reverse(
                        "admin:users_user_change",
                        kwargs={"object_id": from_user.pk},
                    )
                )
        title = f"Transfert des données de {from_user}"
        if to_user:
            title += f" vers {to_user}"
        context = self.admin_site.each_context(request) | {
            "media": self.media,
            "opts": self.opts,
            "form": form,
            "from_user": from_user,
            "to_user": to_user,
            "nothing_to_transfer": not fields_choices,
            "transfer_data": sorted(transfer_data.values(), key=lambda data: data["title"]),
            "title": title,
            "subtitle": None,
            "has_view_permission": self.has_view_permission(request),
        }

        return TemplateResponse(
            request,
            "admin/users/transfer_user.html",
            context,
        )

    def save_model(self, request, obj, form, change):
        if change and not obj.is_active:
            # disable all memberships
            memberships = []
            if obj.is_employer:
                memberships = obj.companymembership_set.all()
            elif obj.is_prescriber:
                memberships = obj.prescribermembership_set.all()
            elif obj.is_labor_inspector:
                memberships = obj.institutionmembership_set.all()
            for membership in memberships:
                if membership.is_active or membership.is_admin:
                    add_support_remark_to_obj(
                        obj,
                        f"Désactivation de {membership} suite à la désactivation de l'utilisateur : "
                        f"is_active={membership.is_active} is_admin={membership.is_admin}",
                    )
                    membership.is_active = False
                    membership.is_admin = False
                    membership.save()
        return super().save_model(request, obj, form, change)


class CertifierFilter(admin.SimpleListFilter):
    title = "Identité certifiée par"
    parameter_name = "certifier"
    not_certified = "not_certified"

    def lookups(self, request, model_admin):
        certifier_choices = list(IdentityCertificationAuthorities.choices)
        certifier_choices.append((self.not_certified, "Non certifié"))
        return certifier_choices

    def queryset(self, request, queryset):
        filter_value = self.value()
        if filter_value == self.not_certified:
            return queryset.exclude(
                Exists(models.IdentityCertification.objects.filter(jobseeker_profile=OuterRef("pk"))),
            )
        elif filter_value:
            return queryset.filter(identity_certifications__certifier=filter_value)
        return queryset


class IdentityCertificationInline(ReadonlyMixin, ItouTabularInline):
    model = models.IdentityCertification
    extra = 0
    fields = ("certifier", "certified_at")
    readonly_fields = fields
    verbose_name = "certification d’identité"
    verbose_name_plural = "certifications d’identité"


@admin.register(models.JobSeekerProfile)
class JobSeekerProfileAdmin(DisabledNotificationsMixin, InconsistencyCheckMixin, ItouModelAdmin):
    """
    Inlines would only be possible the other way around
    """

    class Media:
        css = {"all": ("css/itou-admin.css",)}

    form = JobSeekerProfileAdminForm

    raw_id_fields = (
        "user",
        "birth_place",
        "birth_country",
        "hexa_commune",
        "created_by_prescriber_organization",
    )

    list_display = (
        "pk",
        "user_link",
        "username",
        "birthdate",
        "nir",
        "pole_emploi_id",
    )

    list_filter = (CertifierFilter,)

    list_select_related = ("user",)

    readonly_fields = (
        "hexa_lane_type",
        "hexa_post_code",
        "hexa_commune",
        "pe_obfuscated_nir",
        "pe_last_certification_attempt_at",
        "disabled_notifications",
        "fields_history_formatted",
    )
    show_full_result_count = False

    fieldsets = (
        (
            "Informations",
            {
                "fields": (
                    "user",
                    "asp_uid",
                    "birthdate",
                    "birth_place",
                    "birth_country",
                    "education_level",
                    "nir",
                    "lack_of_nir_reason",
                    "pole_emploi_id",
                    "lack_of_pole_emploi_id_reason",
                    "pole_emploi_since",
                    "unemployed_since",
                    "resourceless",
                    "rqth_employee",
                    "oeth_employee",
                    "pe_obfuscated_nir",
                    "pe_last_certification_attempt_at",
                    "created_by_prescriber_organization",
                    "disabled_notifications",
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
                )
            },
        ),
        (
            "Champs pour les EITI",
            {
                "fields": (
                    "are_allocation_since",
                    "activity_bonus_since",
                    "cape_freelance",
                    "cesa_freelance",
                    "actor_met_for_business_creation",
                    "mean_monthly_income_before_process",
                    "eiti_contributions",
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
        ("Audit", {"fields": ("fields_history_formatted",)}),
    )

    inlines = (
        IdentityCertificationInline,
        PkSupportRemarkInline,
    )

    INCONSISTENCY_CHECKS = [
        (
            "Profil lié à un utilisateur non-candidat",
            lambda q: q.exclude(user__kind=UserKind.JOB_SEEKER),
        ),
    ]

    @admin.display(description="nom complet")
    def username(self, obj):
        return obj.user.get_full_name()

    @admin.display(description="utilisateur")
    def user_link(self, obj):
        return get_admin_view_link(obj.user, content=f"🔗 {obj.user.email}")

    @admin.display(description="historique des champs modifiés sur le modèle")
    def fields_history_formatted(self, obj):
        return format_html("<pre><code>{}</code></pre>", pformat(obj.fields_history, width=120))

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
            search_fields.append("user__email")
            if "@" not in search_term:
                search_fields.append("user__first_name__unaccent")
                search_fields.append("user__last_name__unaccent")
        return search_fields


class EmailAddressWithRemarkAdmin(EmailAddressAdmin):
    inlines = (PkSupportRemarkInline,)


admin.site.unregister(EmailAddress)
admin.site.register(EmailAddress, EmailAddressWithRemarkAdmin)
