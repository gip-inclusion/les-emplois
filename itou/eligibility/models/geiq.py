from collections import Counter

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from itou.eligibility.enums import AdministrativeCriteriaAnnex, AdministrativeCriteriaLevel, AuthorKind
from itou.prescribers.models import PrescriberOrganization
from itou.siaes.enums import SiaeKind
from itou.siaes.models import Siae
from itou.users.models import User

from .common import (
    AbstractAdministrativeCriteria,
    AbstractEligibilityDiagnosisModel,
    CommonEligibilityDiagnosisQuerySet,
)


# GEIQ Eligibility model:
# ---
# Actually very similar to IAE eligibility model.
# First approach was to reuse diagnosis and administrative criteria models with more fields and capabilities.
# On second thought, business rules of GEIQ models are not *yet* clearly defined,
# and will probably be quite different from the ones of IAE eligibility diagnosis.
# Moreover, some validation rules would be tricky to avoid mixing administrative criteria of different kinds.
# Hence a refactor, with a common abstract base for both kind of models (IAE and GEIQ)
# and a specialization with different features for the GEIQ part :
# - new constructor
# - allowance amount and eligibility calculation for the diagnosis
# - parent / child structure and annexes for administrative criteria
# - removal of dependencies on a IAE approval (irrelevant in GEIQ context)
# - ...


class GEIQEligibilityDiagnosisQuerySet(CommonEligibilityDiagnosisQuerySet):
    def authored_by_geiq(self, for_geiq):
        return self.filter(author_geiq=for_geiq)

    def for_job_seeker(self, job_seeker):
        return self.filter(job_seeker=job_seeker).select_related("author", "author_prescriber_organization")


class GEIQEligibilityDiagnosis(AbstractEligibilityDiagnosisModel):

    # Not in abstract model to avoid 'related_name' clashing
    job_seeker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Demandeur d'emploi",
        on_delete=models.CASCADE,
        related_name="geiq_eligibility_diagnoses",
    )
    # Even if GEIQ are technically Siae objects, we keep the same structure as IAE for the author
    author_geiq = models.ForeignKey(
        "siaes.Siae",
        verbose_name="GEIQ de l'auteur",
        related_name="geiq_eligibilitydiagnosis_set",
        null=True,
        blank=True,
        limit_choices_to={"kind": SiaeKind.GEIQ},
        on_delete=models.CASCADE,
    )
    administrative_criteria = models.ManyToManyField(
        "eligibility.GEIQAdministrativeCriteria",
        verbose_name="Critères administratifs GEIQ",
        through="GEIQSelectedAdministrativeCriteria",
        blank=True,
    )

    class Meta:
        verbose_name = "Diagnostic d'éligibilité GEIQ"
        verbose_name_plural = "Diagnostics d'éligibilité GEIQ"
        constraints = [
            models.CheckConstraint(
                name="author_kind_coherence",
                violation_error_message="Le diagnostic d'éligibilité GEIQ ne peut avoir 2 structures pour auteur",
                check=models.Q(
                    author_kind=AuthorKind.GEIQ,
                    author_geiq__isnull=False,
                    author_prescriber_organization__isnull=True,
                )
                | models.Q(
                    author_kind=AuthorKind.PRESCRIBER,
                    author_prescriber_organization__isnull=False,
                    author_geiq__isnull=True,
                ),
            ),
        ]

    objects = GEIQEligibilityDiagnosisQuerySet.as_manager()

    def clean(self):
        if self.author_geiq and self.author_geiq.kind != SiaeKind.GEIQ:
            raise ValidationError(f"La structure auteur du diagnostic n'est pas un GEIQ ({self.author_geiq.kind})")

    def _get_eligibility_and_allowance_amount(self) -> tuple[bool, int]:
        if self.author_kind == AuthorKind.PRESCRIBER and self.author_prescriber_organization:
            return True, 1400

        administrative_criteria = self.administrative_criteria.all()
        # Count by annex
        annex_cnt = Counter(c.annex for c in administrative_criteria)
        # Only annex 2 administrative criteria have a level defined
        level_cnt = Counter(c.level for c in administrative_criteria if c.level)
        eligibility, amount = False, 0

        if annex_cnt["1"] > 0:
            eligibility, amount = True, 814

        if level_cnt["1"] > 0:
            # At least one level 1 criterion
            eligibility, amount = True, max(amount, 1400)

        if level_cnt["2"] > 1:
            # At least two level 2 criteria
            eligibility, amount = True, max(amount, 1400)

        return eligibility, amount

    @property
    def eligibility_confirmed(self) -> bool:
        """
        GEIQ elibility.
        Calculated in function of:
            - author kind
            - number, annex and level of administrative criteria.
        """
        eligibility, _ = self._get_eligibility_and_allowance_amount()

        return eligibility

    @property
    def allowance_amount(self) -> int:
        """
        Amount of granted allowance for job seeker.
        Calculated in function of:
            - author kind
            - number, annex and level of administrative criteria.
        Currently, only 3 amounts possible:
            - 0
            - 814EUR
            - 1400EUR
        """

        _, amount = self._get_eligibility_and_allowance_amount()

        return amount

    @classmethod
    @transaction.atomic()
    def create_eligibility_diagnosis(
        cls,
        job_seeker: User,
        author: User,
        author_structure: Siae | PrescriberOrganization,
        administrative_criteria=(),
    ):
        author_org = author_geiq = author_kind = None

        if isinstance(author_structure, PrescriberOrganization):
            author_org = author_structure
            author_kind = AuthorKind.PRESCRIBER
        elif isinstance(author_structure, Siae) and author_structure.kind == SiaeKind.GEIQ:
            author_geiq = author_structure
            author_kind = AuthorKind.GEIQ
        else:
            raise ValueError(
                f"Impossible de créer un diagnostic GEIQ avec une structure de type "
                f"{author_structure.__class__.__name__}"
            )

        result = cls.objects.create(
            job_seeker=job_seeker,
            author=author,
            author_kind=author_kind,
            author_prescriber_organization=author_org,
            author_geiq=author_geiq,
        )

        if administrative_criteria:
            result.administrative_criteria.set(administrative_criteria)

        return result


class GEIQAdministrativeCriteria(AbstractAdministrativeCriteria):
    parent = models.ForeignKey(
        "self",
        verbose_name="Critère parent",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
    )
    annex = models.CharField(
        verbose_name="Annexe",
        max_length=1,
        choices=AdministrativeCriteriaAnnex.choices,
        default=AdministrativeCriteriaAnnex.ANNEX_1,
    )
    level = models.CharField(
        verbose_name="Niveau",
        max_length=1,
        choices=AdministrativeCriteriaLevel.choices,
        # as opposed to IAE, level can be null (annex 1)
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "Critère administratif GEIQ"
        verbose_name_plural = "Critères administratifs GEIQ"
        ordering = [models.F("level").asc(nulls_last=True), "ui_rank"]
        constraints = [
            models.CheckConstraint(
                name="ac_level_annex_coherence",
                violation_error_message="Incohérence entre l'annexe du critère administratif et son niveau",
                check=models.Q(annex=AdministrativeCriteriaAnnex.ANNEX_1, level__isnull=True)
                | models.Q(annex=AdministrativeCriteriaAnnex.ANNEX_2, level__isnull=False),
            ),
        ]


class GEIQSelectedAdministrativeCriteria(models.Model):

    eligibility_diagnosis = models.ForeignKey(
        GEIQEligibilityDiagnosis,
        on_delete=models.CASCADE,
    )
    administrative_criteria = models.ForeignKey(
        GEIQAdministrativeCriteria,
        on_delete=models.CASCADE,
        related_name="administrative_criteria_through",
    )
    created_at = models.DateTimeField(verbose_name="Date de création", default=timezone.now)

    class Meta:
        verbose_name = "Critère administratif GEIQ sélectionné"
        verbose_name_plural = "Critères administratifs GEIQ sélectionnés"
        unique_together = ("eligibility_diagnosis", "administrative_criteria")

    def __str__(self):
        return f"{self.pk}"
