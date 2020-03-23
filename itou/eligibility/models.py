import logging

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from itou.utils.perms.user import KIND_JOB_SEEKER, KIND_PRESCRIBER, KIND_SIAE_STAFF


logger = logging.getLogger(__name__)


class EligibilityDiagnosis(models.Model):
    """
    Store the eligibility diagnosis of a job seeker.
    """

    AUTHOR_KIND_JOB_SEEKER = KIND_JOB_SEEKER
    AUTHOR_KIND_PRESCRIBER = KIND_PRESCRIBER
    AUTHOR_KIND_SIAE_STAFF = KIND_SIAE_STAFF

    AUTHOR_KIND_CHOICES = (
        (AUTHOR_KIND_JOB_SEEKER, _("Demandeur d'emploi")),
        (AUTHOR_KIND_PRESCRIBER, _("Prescripteur")),
        (AUTHOR_KIND_SIAE_STAFF, _("Employeur (SIAE)")),
    )

    job_seeker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Demandeur d'emploi"),
        on_delete=models.CASCADE,
        related_name="eligibility_diagnoses",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Auteur"),
        on_delete=models.CASCADE,
        related_name="eligibility_diagnoses_made",
    )
    author_kind = models.CharField(
        verbose_name=_("Type de l'auteur"), max_length=10, choices=AUTHOR_KIND_CHOICES, default=AUTHOR_KIND_PRESCRIBER
    )
    # When the author is an SIAE staff member, keep a track of his current SIAE.
    author_siae = models.ForeignKey(
        "siaes.Siae", verbose_name=_("SIAE de l'auteur"), null=True, blank=True, on_delete=models.CASCADE
    )
    # When the author is a prescriber, keep a track of his current organization (if any).
    author_prescriber_organization = models.ForeignKey(
        "prescribers.PrescriberOrganization",
        verbose_name=_("Organisation du prescripteur de l'auteur"),
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )

    created_at = models.DateTimeField(verbose_name=_("Date de création"), default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(verbose_name=_("Date de modification"), blank=True, null=True, db_index=True)

    class Meta:
        verbose_name = _("Diagnostic d'éligibilité")
        verbose_name_plural = _("Diagnostics d'éligibilité")
        ordering = ["-created_at"]

    def __str__(self):
        return str(self.id)

    def save(self, *args, **kwargs):
        self.updated_at = timezone.now()
        return super().save(*args, **kwargs)

    @classmethod
    def create_diagnosis(cls, job_seeker, user_info, **fields):
        """
        Keyword arguments:
            job_seeker: User() object
            user_info: UserInfo namedtuple (itou.utils.perms.user.get_user_info)
        """
        return cls.objects.create(
            job_seeker=job_seeker,
            author=user_info.user,
            author_kind=user_info.kind,
            author_siae=user_info.siae,
            author_prescriber_organization=user_info.prescriber_organization,
        )


class AdministrativeCriteriaLevel1(models.Model):

    EXTRA_DATA = {
        "is_beneficiaire_du_rsa": {"written_proof": _("Attestation RSA")},
        "is_allocataire_ass": {"written_proof": _("Attestation ASS")},
        "is_allocataire_aah": {"written_proof": _("Attestation AAH")},
        "is_detld_24_mois": {"written_proof": _("Attestation Pôle emploi")},
    }

    eligibility_diagnosis = models.OneToOneField(EligibilityDiagnosis, on_delete=models.CASCADE)
    is_beneficiaire_du_rsa = models.BooleanField(
        verbose_name=_("Bénéficiaire du RSA"), default=False, help_text=_("Revenu de solidarité active")
    )
    is_allocataire_ass = models.BooleanField(
        verbose_name=_("Allocataire ASS"), default=False, help_text=_("Allocation de solidarité spécifique")
    )
    is_allocataire_aah = models.BooleanField(
        verbose_name=_("Allocataire AAH"), default=False, help_text=_("Allocation aux adultes handicapés")
    )
    is_detld_24_mois = models.BooleanField(
        verbose_name=_("DETLD (+ 24 mois)"),
        default=False,
        help_text=_("Demandeur d'emploi de très longue durée (inscrit à Pôle emploi)"),
    )
    created_at = models.DateTimeField(verbose_name=_("Date de création"), default=timezone.now, db_index=True)

    class Meta:
        verbose_name = _("Critères administratifs de niveau 1")
        verbose_name_plural = _("Critères administratifs de niveau 1")

    def __str__(self):
        return str(self.id)


class AdministrativeCriteriaLevel2(models.Model):

    EXTRA_DATA = {
        "is_niveau_detude_3_infra": {"written_proof": _("Diplôme et/ou attestation sur l'honneur")},
        "is_senior_50_ans": {"written_proof": _("Pièce d'identité")},
        "is_jeune_26_ans": {"written_proof": _("Pièce d'identité")},
        "is_sortant_de_lase": {"written_proof": _("Attestation ASE")},
        "is_deld": {"written_proof": _("Attestation Pôle emploi")},
        "is_travailleur_handicape": {"written_proof": _("Attestation reconnaissance qualité TH")},
        "is_parent_isole": {"written_proof": _("Attestation CAF")},
        "is_sans_hebergement": {"written_proof": _("Attestation sur l'honneur")},
        "is_primo_arrivant": {"written_proof": _("Contrat d'intégration républicaine de moins de 24 mois")},
        "is_resident_zrr": {
            "written_proof": _("Justificatif de domicile"),
            "written_proof_url": "https://www.data.gouv.fr/fr/datasets/zones-de-revitalisation-rurale-zrr/​",
        },
        "is_resident_qpv": {
            "written_proof": _("Justificatif de domicile"),
            "written_proof_url": "https://sig.ville.gouv.fr/​",
        },
    }

    eligibility_diagnosis = models.OneToOneField(EligibilityDiagnosis, on_delete=models.CASCADE)
    is_niveau_detude_3_infra = models.BooleanField(verbose_name=_("Niveau d'étude 3 ou infra"), default=False)
    is_senior_50_ans = models.BooleanField(verbose_name=_("Senior (+50 ans)"), default=False)
    is_jeune_26_ans = models.BooleanField(verbose_name=_("Jeunes (-26 ans)"), default=False)
    is_sortant_de_lase = models.BooleanField(
        verbose_name=_("Sortant de l'ASE"), default=False, help_text=_("Aide sociale à l'enfance")
    )
    is_deld = models.BooleanField(
        verbose_name=_("DELD (12-24 mois)"),
        default=False,
        help_text=_("Demandeur d'emploi de très longue durée (inscrit à Pôle emploi)"),
    )
    is_travailleur_handicape = models.BooleanField(verbose_name=_("Travailleur handicapé"), default=False)
    is_parent_isole = models.BooleanField(verbose_name=_("Parent isolé"), default=False)
    is_sans_hebergement = models.BooleanField(
        verbose_name=_("Personne sans hébergement ou hébergée ou ayant un parcours de rue"), default=False
    )
    is_primo_arrivant = models.BooleanField(verbose_name=_("Primo arrivant"), default=False)
    is_resident_zrr = models.BooleanField(
        verbose_name=_("Résident ZRR"), default=False, help_text=_("Zone de revitalisation rurale")
    )
    is_resident_qpv = models.BooleanField(
        verbose_name=_("Résident QPV"), default=False, help_text=_("Quartier prioritaire de la politique de la ville")
    )
    created_at = models.DateTimeField(verbose_name=_("Date de création"), default=timezone.now, db_index=True)

    class Meta:
        verbose_name = _("Critères administratifs de niveau 2")
        verbose_name_plural = _("Critères administratifs de niveau 2")

    def __str__(self):
        return str(self.id)
