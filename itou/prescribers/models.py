from django.conf import settings
from django.contrib.postgres.search import TrigramSimilarity
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from itou.utils.address.models import AddressMixin
from itou.utils.emails import get_email_message
from itou.utils.tokens import generate_random_token
from itou.utils.validators import validate_siret


class PrescriberOrganizationQuerySet(models.QuerySet):
    def member_required(self, user):
        if user.is_superuser:
            return self
        return self.filter(members=user, members__is_active=True)

    def autocomplete(self, search_string, limit=10):
        queryset = (
            self.annotate(similarity=TrigramSimilarity("name", search_string))
            .filter(similarity__gt=0.1)
            .order_by("-similarity")
        )
        return queryset[:limit]

    def by_safir_code(self, safir_code):
        return self.filter(code_safir_pole_emploi=safir_code).first()


class PrescriberOrganization(AddressMixin):  # Do not forget the mixin!
    """
    The organization of a prescriber, e.g.: Pôle emploi, missions locales, Cap emploi etc.

    Note: it is not required for a prescriber to be a member of an organization.
    """

    class Kind(models.TextChoices):
        PE = "PE", _("Pôle emploi")
        CAP_EMPLOI = "CAP_EMPLOI", _("CAP emploi")
        ML = "ML", _("Mission locale")
        DEPT = "DEPT", _("Service social du conseil départemental")
        SPIP = "SPIP", _("SPIP - Service pénitentiaire d'insertion et de probation")
        PJJ = "PJJ", _("PJJ - Protection judiciaire de la jeunesse")
        CCAS = "CCAS", _("CCAS - Centre communal d'action sociale ou centre intercommunal d'action sociale")
        PLIE = "PLIE", _("PLIE - Plan local pour l'insertion et l'emploi")
        CHRS = "CHRS", _("CHRS - Centre d'hébergement et de réinsertion sociale")
        CIDFF = "CIDFF", _("CIDFF - Centre d'information sur les droits des femmes et des familles")
        PREVENTION = "PREVENTION", _("Service ou club de prévention")
        AFPA = "AFPA", _("AFPA - Agence nationale pour la formation professionnelle des adultes")
        PIJ_BIJ = "PIJ_BIJ", _("PIJ-BIJ - Point/Bureau information jeunesse")
        CAF = "CAF", _("CAF - Caisse d'allocation familiale")
        CADA = "CADA", _("CADA - Centre d'accueil de demandeurs d'asile")
        ASE = "ASE", _("ASE - Aide sociale à l'enfance")
        CAVA = "CAVA", _("CAVA - Centre d'adaptation à la vie active")
        CPH = "CPH", _("CPH - Centre provisoire d'hébergement")
        CHU = "CHU", _("CHU - Centre d'hébergement d'urgence")
        OACAS = (
            "OACAS",
            _(
                "OACAS - Structure porteuse d'un agrément national organisme "
                "d'accueil communautaire et d'activité solidaire"
            ),
        )
        OTHER = "OTHER", _("Autre structure")

    class AuthorizationStatus(models.TextChoices):
        NOT_SET = "NOT_SET", _("Habilitation en attente de validation")
        VALIDATED = "VALIDATED", _("Habilitation validée")
        REFUSED = "REFUSED", _("Validation de l'habilitation refusée")
        NOT_REQUIRED = "NOT_REQUIRED", _("Pas d'habilitation nécessaire")

    siret = models.CharField(verbose_name=_("Siret"), max_length=14, validators=[validate_siret], blank=True)
    kind = models.CharField(verbose_name=_("Type"), max_length=20, choices=Kind.choices, default=Kind.OTHER)
    name = models.CharField(verbose_name=_("Nom"), max_length=255)
    phone = models.CharField(verbose_name=_("Téléphone"), max_length=20, blank=True)
    email = models.EmailField(verbose_name=_("E-mail"), blank=True)
    website = models.URLField(verbose_name=_("Site web"), blank=True)
    description = models.TextField(verbose_name=_("Description"), blank=True)
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL, verbose_name=_("Membres"), through="PrescriberMembership", blank=True
    )
    secret_code = models.CharField(
        verbose_name=_("Code secret"),
        help_text=_("Code permettant à un utilisateur de rejoindre l'organisation."),
        max_length=6,
        default=generate_random_token,
        unique=True,
    )
    is_authorized = models.BooleanField(
        verbose_name=_("Habilitation"),
        default=False,
        help_text=_("Précise si l'organisation est habilitée par le préfet."),
    )
    code_safir_pole_emploi = models.CharField(
        verbose_name=_("Code Safir"),
        help_text=_("Code unique d'une agence Pole emploi."),
        validators=[RegexValidator("^[0-9]{5}$", message=_("Le code SAFIR est erroné"))],
        max_length=5,
        null=True,
        unique=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Créé par"),
        related_name="created_prescriber_organization_set",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    created_at = models.DateTimeField(verbose_name=_("Date de création"), default=timezone.now)
    updated_at = models.DateTimeField(verbose_name=_("Date de modification"), blank=True, null=True)

    authorization_status = models.CharField(
        verbose_name=_("Statut de l'habilitation"),
        max_length=20,
        choices=AuthorizationStatus.choices,
        default=AuthorizationStatus.NOT_SET,
    )
    authorization_updated_at = models.DateTimeField(
        verbose_name=_("Date de MAJ du statut de l'habilitation"), null=True
    )
    authorization_updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Dernière MAJ de l'habilitation par"),
        related_name="authorization_status_set",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    objects = models.Manager.from_queryset(PrescriberOrganizationQuerySet)()

    class Meta:
        verbose_name = _("Organisation")
        verbose_name_plural = _("Organisations")

    def __str__(self):
        return f"{self.name}"

    def save(self, *args, **kwargs):
        if self.pk:
            self.updated_at = timezone.now()
        return super().save(*args, **kwargs)

    @property
    def display_name(self):
        return self.name.capitalize()

    @property
    def has_members(self):
        return self.active_members.exists()

    @property
    def active_members(self):
        return self.members.filter(is_active=True)

    @property
    def has_unset_authorization(self):
        return self.authorization_status == PrescriberOrganization.AuthorizationStatus.NOT_SET

    def new_signup_warning_email_to_existing_members(self, user):
        """
        Send a warning fyi-only email to all existing users of the organization
        about a new user signup.
        """
        to = [u.email for u in self.active_members]
        context = {"new_user": user, "organization": self}
        subject = "prescribers/email/new_signup_warning_email_to_existing_members_subject.txt"
        body = "prescribers/email/new_signup_warning_email_to_existing_members_body.txt"
        return get_email_message(to, context, subject, body)

    def validated_prescriber_organization_email(self):
        """
        Send an email to the user who asked for the validation
        of a new prescriber organization
        """
        to = [u.email for u in self.active_members]
        context = {"organization": self}
        subject = "prescribers/email/validated_prescriber_organization_email_subject.txt"
        body = "prescribers/email/validated_prescriber_organization_email_body.txt"
        return get_email_message(to, context, subject, body)

    def refused_prescriber_organization_email(self):
        """
        Send an email to the user who asked for the validation
        of a new prescriber organization when refused
        """
        to = [u.email for u in self.active_members]
        context = {"organization": self}
        subject = "prescribers/email/refused_prescriber_organization_email_subject.txt"
        body = "prescribers/email/refused_prescriber_organization_email_body.txt"
        return get_email_message(to, context, subject, body)

    def must_validate_prescriber_organization_email(self):
        """
        Send an email to the support:
        signup of a new prescriber organization, with unregistered/unchecked org
        => prescriber organization authorization must be validated
        """
        to = [settings.ITOU_EMAIL_CONTACT]
        context = {"organization": self}
        subject = "prescribers/email/must_validate_prescriber_organization_email_subject.txt"
        body = "prescribers/email/must_validate_prescriber_organization_email_body.txt"
        return get_email_message(to, context, subject, body)


class PrescriberMembership(models.Model):
    """Intermediary model between `User` and `PrescriberOrganization`."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    organization = models.ForeignKey(PrescriberOrganization, on_delete=models.CASCADE)
    joined_at = models.DateTimeField(verbose_name=_("Date d'adhésion"), default=timezone.now)
    is_admin = models.BooleanField(verbose_name=_("Administrateur de la structure d'accompagnement"), default=False)
