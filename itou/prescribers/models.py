from django.conf import settings
from django.contrib.gis.measure import D
from django.contrib.postgres.search import TrigramSimilarity
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils.http import urlencode

from itou.common_apps.address.models import AddressMixin
from itou.common_apps.organizations.models import MembershipAbstract, OrganizationAbstract, OrganizationQuerySet
from itou.utils.emails import get_email_message
from itou.utils.urls import get_absolute_url
from itou.utils.validators import validate_code_safir, validate_siret


class PrescriberOrganizationQuerySet(OrganizationQuerySet):
    def autocomplete(self, search_string, limit=10):
        queryset = (
            self.annotate(similarity=TrigramSimilarity("name", search_string))
            .filter(similarity__gt=0.1)
            .order_by("-similarity")
        )
        return queryset[:limit]

    def by_safir_code(self, safir_code):
        return self.filter(code_safir_pole_emploi=safir_code).first()

    def within(self, point, distance_km):
        return self.filter(coords__dwithin=(point, D(km=distance_km)))


class PrescriberOrganizationManager(models.Manager):
    def get_accredited_orgs_for(self, org):
        """
        Returns organizations accredited by the given organization.
        """
        if org.kind == self.model.Kind.DEPT and org.is_authorized:
            return self.filter(department=org.department, is_brsa=True)
        return self.none()


class PrescriberOrganization(AddressMixin, OrganizationAbstract):
    """
    The organization of a prescriber, e.g.: Pôle emploi, missions locales, Cap emploi etc.

    A "prescriber" is always represented by a User object with the `is_prescriber` flag set to `True`.

    The "prescriber" has the possibility of being a member of an organization represented by a
    `PrescriberOrganization` object through `PrescriberMembership`.

    However it is not required for a "prescriber" to be a member of an organization.

    There are 3 possible cases:

    Case 1
        A "prescriber" is alone (e.g. "éducateur de rue"). In this case there is only a `User` object
            - User.is_prescriber = True

    Case 2
        A "prescriber" is a member of an organization (e.g. an association of unemployed people etc.)
        and uses the platform with 0 or n collaborators.
        In this case there are 3 objects:
            - User.is_prescriber = True
            - PrescriberOrganization.is_authorized = False
            - PrescriberMembership

    Case 3
        This case is a variant of case 2 where the organization is "authorized" at national level or by
        the Prefect (e.g. Pôle emploi, CCAS, Cap emploi…). This is similar to case 2  with an additional
        flag for the organization:
            - User.is_prescriber = True
            - PrescriberOrganization.is_authorized = True
            - PrescriberMembership

    In the last 2 cases, there can be n members by organization.

    In case 1 and case 2, we talk about "orienteur" in French.

    In case 3, we talk about "prescripteur habilité" in French.
    """

    class Kind(models.TextChoices):
        CAP_EMPLOI = "CAP_EMPLOI", "CAP emploi"
        ML = "ML", "Mission locale"
        OIL = "OIL", "Opérateur d'intermédiation locative"
        ODC = "ODC", "Organisation délégataire d'un CD"
        PENSION = "PENSION", "Pension de famille / résidence accueil"
        PE = "PE", "Pôle emploi"
        RS_FJT = "RS_FJT", "Résidence sociale / FJT - Foyer de Jeunes Travailleurs"
        PREVENTION = "PREVENTION", "Service ou club de prévention"
        DEPT = "DEPT", "Service social du conseil départemental"
        AFPA = ("AFPA", "AFPA - Agence nationale pour la formation professionnelle des adultes")
        ASE = "ASE", "ASE - Aide sociale à l'enfance"
        CAARUD = (
            "CAARUD",
            ("CAARUD - Centre d'accueil et d'accompagnement à la réduction de risques pour usagers de drogues"),
        )
        CADA = "CADA", "CADA - Centre d'accueil de demandeurs d'asile"
        CAF = "CAF", "CAF - Caisse d'allocations familiales"
        CAVA = "CAVA", "CAVA - Centre d'adaptation à la vie active"
        CCAS = ("CCAS", "CCAS - Centre communal d'action sociale ou centre intercommunal d'action sociale")
        CHRS = "CHRS", "CHRS - Centre d'hébergement et de réinsertion sociale"
        CHU = "CHU", "CHU - Centre d'hébergement d'urgence"
        CIDFF = ("CIDFF", "CIDFF - Centre d'information sur les droits des femmes et des familles")
        CPH = "CPH", "CPH - Centre provisoire d'hébergement"
        CSAPA = "CSAPA", "CSAPA - Centre de soins, d'accompagnement et de prévention en addictologie"
        E2C = "E2C", "E2C - École de la deuxième chance"
        EPIDE = "EPIDE", "EPIDE - Établissement pour l'insertion dans l'emploi"
        HUDA = "HUDA", "HUDA - Hébergement d'urgence pour demandeurs d'asile"
        MSA = "MSA", "MSA - Mutualité Sociale Agricole"
        OACAS = (
            "OACAS",
            (
                "OACAS - Structure porteuse d'un agrément national organisme "
                "d'accueil communautaire et d'activité solidaire"
            ),
        )
        PIJ_BIJ = "PIJ_BIJ", "PIJ-BIJ - Point/Bureau information jeunesse"
        PJJ = "PJJ", "PJJ - Protection judiciaire de la jeunesse"
        PLIE = "PLIE", "PLIE - Plan local pour l'insertion et l'emploi"
        SPIP = "SPIP", "SPIP - Service pénitentiaire d'insertion et de probation"
        OTHER = "Autre", "Autre"

    class AuthorizationStatus(models.TextChoices):
        NOT_SET = "NOT_SET", "Habilitation en attente de validation"
        VALIDATED = "VALIDATED", "Habilitation validée"
        REFUSED = "REFUSED", "Validation de l'habilitation refusée"
        NOT_REQUIRED = "NOT_REQUIRED", "Pas d'habilitation nécessaire"

    # Rules:
    # - a SIRET was not mandatory in the past (some entries still have a "blank" siret)
    # - a SIRET is now required for all organizations, except for Pôle emploi agencies
    # - a SIRET now can have several kinds
    # This is enforced at the DB level with a `unique_together` constraint + `null=True`.
    # `null=True` is required to avoid unique constraint violations when saving multiple
    # objects with "blank" values (e.g. Pôle emploi agencies or old entries that existed
    # prior to the mandatory siret).
    # See https://docs.djangoproject.com/en/3.1/ref/models/fields/#null
    siret = models.CharField(verbose_name="Siret", max_length=14, validators=[validate_siret], null=True, blank=True)
    is_head_office = models.BooleanField(
        verbose_name="Siège de l'entreprise", default=False, help_text="Information obtenue via API Entreprise."
    )
    kind = models.CharField(verbose_name="Type", max_length=20, choices=Kind.choices, default=Kind.OTHER)
    is_brsa = models.BooleanField(
        verbose_name="Conventionné pour le suivi des BRSA",
        default=False,
        help_text="Indique si l'organisme est conventionné par le conseil départemental pour le suivi des BRSA.",
    )
    phone = models.CharField(verbose_name="Téléphone", max_length=20, blank=True)
    email = models.EmailField(verbose_name="E-mail", blank=True)
    website = models.URLField(verbose_name="Site web", blank=True)
    description = models.TextField(verbose_name="Description", blank=True)
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        verbose_name="Membres",
        through="PrescriberMembership",
        blank=True,
        through_fields=("organization", "user"),
    )
    is_authorized = models.BooleanField(
        verbose_name="Habilitation",
        default=False,
        help_text="Précise si l'organisation est habilitée par le Préfet.",
    )
    code_safir_pole_emploi = models.CharField(
        verbose_name="Code Safir",
        help_text="Code unique d'une agence Pole emploi.",
        validators=[validate_code_safir],
        max_length=5,
        blank=True,
        # Empty values are stored as NULL if both `null=True` and `unique=True` are set.
        # This avoids unique constraint violations when saving multiple objects with blank values.
        null=True,
        unique=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Créé par",
        related_name="created_prescriber_organization_set",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    authorization_status = models.CharField(
        verbose_name="Statut de l'habilitation",
        max_length=20,
        choices=AuthorizationStatus.choices,
        default=AuthorizationStatus.NOT_SET,
    )
    authorization_updated_at = models.DateTimeField(verbose_name="Date de MAJ du statut de l'habilitation", null=True)
    authorization_updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Dernière MAJ de l'habilitation par",
        related_name="authorization_status_set",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    objects = PrescriberOrganizationManager.from_queryset(PrescriberOrganizationQuerySet)()

    class Meta:
        verbose_name = "Organisation"
        verbose_name_plural = "Organisations"
        # This DB constraint works with null fields, but not with blank ones
        # If both org1 and org2 are created:
        # OK  => org1: (kind="ML", siret=None) + org2: (kind="ML", siret=None)
        # OK  => org1: (kind="ML", siret="12345678900000") + org2; (kind="ML", siret=None)
        # OK =>  org1: (kind="ML", siret="12345678900000") + org2; (kind="PLIE", siret="12345678900000")
        # NOK => org1: (kind="ML", siret="12345678900000") + org2; (kind="ML", siret="12345678900000")
        unique_together = ("siret", "kind")

    def clean(self, *args, **kwargs):
        super().clean()
        self.clean_code_safir_pole_emploi()
        self.clean_siret()

    def clean_code_safir_pole_emploi(self):
        """
        A code SAFIR can only be set for PE agencies.
        """
        if self.kind != self.Kind.PE and self.code_safir_pole_emploi:
            raise ValidationError({"code_safir_pole_emploi": "Le Code Safir est réservé aux agences Pôle emploi."})

    def clean_siret(self):
        """
        SIRET is required for all organizations, except for PE agencies.
        """
        if self.kind != self.Kind.PE:
            if not self.siret:
                raise ValidationError({"siret": "Le SIRET est obligatoire."})
            if self._meta.model.objects.exclude(pk=self.pk).filter(siret=self.siret, kind=self.kind).exists():
                raise ValidationError({"siret": "Ce SIRET est déjà utilisé."})

    @property
    def accept_survey_url(self):
        """
        Returns the typeform's satisfaction survey URL to be sent after a successful hiring.
        """
        args = {
            "idorganisation": self.pk,
            "region": self.region or "",
            "typeorga": self.get_kind_display(),
            "departement": self.department or "",
        }
        qs = urlencode(args)
        return f"{settings.TYPEFORM_URL}/to/EDHZSU7p?{qs}"

    def get_card_url(self):
        if not self.is_authorized:
            return None
        return reverse("prescribers_views:card", kwargs={"org_id": self.pk})

    def has_refused_authorization(self):
        return self.authorization_status == self.AuthorizationStatus.REFUSED

    def has_pending_authorization(self):
        """
        Pending manual verification of authorization by support staff.
        """
        return self.authorization_status == self.AuthorizationStatus.NOT_SET

    def has_pending_authorization_proof(self):
        """
        An unknown organization claiming to be authorized must provide a written proof.
        """
        return self.kind == self.Kind.OTHER and self.authorization_status == self.AuthorizationStatus.NOT_SET

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
        signup of a **newly created** prescriber organization, with unregistered/unchecked org
        => prescriber organization authorization must be validated
        """
        to = [settings.ITOU_EMAIL_CONTACT]
        context = {"organization": self}
        subject = "prescribers/email/must_validate_prescriber_organization_email_subject.txt"
        body = "prescribers/email/must_validate_prescriber_organization_email_body.txt"
        return get_email_message(to, context, subject, body)


class PrescriberMembership(MembershipAbstract):
    """Intermediary model between `User` and `PrescriberOrganization`."""

    organization = models.ForeignKey(PrescriberOrganization, on_delete=models.CASCADE)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="updated_prescribermembership_set",
        null=True,
        on_delete=models.CASCADE,
        verbose_name="Mis à jour par",
    )

    class Meta:
        unique_together = ("user_id", "organization_id")

    def request_for_invitation(self, requestor: dict):
        """
        A new user can ask for an invitation to join a prescriber organization.
        The list of members is sorted by:
        - admin
        - date joined
        and the first member of the list will be contacted.
        This feature is only available for prescribers but it should
        be common to every organization.
        """
        to_user = self.user
        to = [to_user.email]
        invitation_url = "%s?%s" % (reverse("invitations_views:invite_prescriber_with_org"), urlencode(requestor))
        # requestor is not a User, get_full_name can't be used in template
        full_name = f"""{requestor.get("first_name")} {requestor.get("last_name")}"""
        context = {
            "to": to_user,
            "organization": self.organization,
            "requestor": requestor,
            "full_name": full_name,
            "email": requestor.get("email"),
            "invitation_url": get_absolute_url(invitation_url),
        }
        subject = "common/emails/request_for_invitation_subject.txt"
        body = "common/emails/request_for_invitation_body.txt"
        return get_email_message(to, context, subject, body)
