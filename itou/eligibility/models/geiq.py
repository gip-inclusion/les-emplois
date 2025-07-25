from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from django.utils.text import slugify

from itou.companies.enums import CompanyKind
from itou.companies.models import Company
from itou.eligibility.enums import AdministrativeCriteriaAnnex, AdministrativeCriteriaLevel, AuthorKind
from itou.eligibility.models.common import (
    AbstractAdministrativeCriteria,
    AbstractEligibilityDiagnosisModel,
    AbstractSelectedAdministrativeCriteria,
    CommonEligibilityDiagnosisQuerySet,
)
from itou.eligibility.utils import geiq_allowance_amount
from itou.gps.models import FollowUpGroup
from itou.prescribers.models import PrescriberOrganization
from itou.users.models import User


# GEIQ Eligibility model:
# ---
# Actually very similar to IAE eligibility model.
# First approach was to reuse diagnosis and administrative criteria models with more fields and capabilities.
# On second thought, business rules of GEIQ models are not *yet* clearly defined,
# and will probably be quite different from the ones of IAE eligibility diagnosis.
# Moreover, some validation rules would be tricky to avoid mixing administrative criteria of different kinds.
# Hence a refactor, with a common abstract base for both kind of models (IAE and GEIQ)
# and a specialization with different features for the GEIQ part :
# - new constructor / update methods
# - allowance amount and eligibility calculation for the diagnosis
# - parent / child structure and annexes for administrative criteria (for templates)
# - removal of dependencies on an IAE approval (irrelevant in GEIQ context)
# - ...


class GEIQEligibilityDiagnosisQuerySet(CommonEligibilityDiagnosisQuerySet):
    def authored_by_prescriber_or_geiq(self, geiq):
        return self.filter(models.Q(author_geiq=geiq) | models.Q(author_prescriber_organization__isnull=False))

    def diagnoses_for(self, job_seeker, for_geiq=None, for_job_seeker=False):
        # Get *all* GEIQ diagnoses for given job seeker (even expired)
        # When for_job_seeker=False, fetch only diagnoses from authorized prescribers, or
        # from a specified GEIQ; otherwise fetch all diagnoses.
        query = (
            self.filter(job_seeker=job_seeker)
            .select_related("author", "author_geiq", "author_prescriber_organization")
            .prefetch_related("administrative_criteria")
            # Ordering by created_at is sufficient, because GEIQ can’t create a GEIQEligibilityDiagnosis
            # when there exists a valid GEIQEligibilityDiagnosis from an authorized prescriber.
            .order_by("-created_at")
        )
        if not for_job_seeker:
            query = query.authored_by_prescriber_or_geiq(for_geiq)

        return query

    def valid_diagnoses_for(self, job_seeker, for_geiq=None):
        # Get *valid* (non-expired) GEIQ diagnoses for given job seeker
        # This is the to-go method to get the "current" GEIQ diagnosis for a job seeker:
        # `GEIQEligibilityDiagnosis.objects.valid_diagnoses_for(my_job_seeker, optional_geiq).first()`
        return self.valid().diagnoses_for(job_seeker, for_geiq)


class GEIQEligibilityDiagnosis(AbstractEligibilityDiagnosisModel):
    # Not in abstract model to avoid 'related_name' clashing
    job_seeker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="demandeur d'emploi",
        on_delete=models.CASCADE,
        related_name="geiq_eligibility_diagnoses",
    )
    # Even if GEIQ are technically Siae objects, we keep the same structure as IAE for the author
    author_geiq = models.ForeignKey(
        "companies.Company",
        verbose_name="GEIQ de l'auteur",
        related_name="geiq_eligibilitydiagnosis_set",
        null=True,
        blank=True,
        limit_choices_to={"kind": CompanyKind.GEIQ},
        on_delete=models.RESTRICT,  # For traceability and accountability
    )
    administrative_criteria = models.ManyToManyField(
        "eligibility.GEIQAdministrativeCriteria",
        verbose_name="critères administratifs GEIQ",
        through="GEIQSelectedAdministrativeCriteria",
        blank=True,
    )

    class Meta:
        verbose_name = "diagnostic d'éligibilité GEIQ"
        verbose_name_plural = "diagnostics d'éligibilité GEIQ"
        constraints = [
            models.CheckConstraint(
                name="author_kind_coherence",
                violation_error_message="La structure de l'auteur ne correspond pas à son type",
                condition=models.Q(
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
        if self.author_geiq and self.author_geiq.kind != CompanyKind.GEIQ:
            raise ValidationError("L'auteur du diagnostic n'est pas un GEIQ")

        if self.pk:
            return

        # The following would have been nice in a unique constraint,
        # but infortunately functions.Now() is not immutable
        if (
            self.job_seeker_id
            and GEIQEligibilityDiagnosis.objects.valid_diagnoses_for(self.job_seeker, self.author_geiq).exists()
        ):
            raise ValidationError(f"Il existe déjà un diagnostic GEIQ valide pour cet utilisateur : {self.job_seeker}")

    def _invalidate_obsolete_geiq_diagnoses(self):
        # If: there are one or more valid GEIQ authored diagnoses for a given job seeker
        # And: we want to create a GEIQ diagnosis made by an authorized prescriber for this same job seeker
        # Then: all valid GEIQ authored diagnosis with no *hiring attached* are "disabled" (i.e. forced to expire)
        # => A diagnosis made by a prescriber have a higher priority than GEIQ ones, making them obsolete.

        if self.author_prescriber_organization and self.is_valid:
            obsolete_geiq_diagnoses = (
                # valid / non-expired only
                GEIQEligibilityDiagnosis.objects.valid().filter(
                    job_seeker=self.job_seeker,
                    # authored by a GEIQ and have no job application attached
                    author_geiq__isnull=False,
                    job_applications__isnull=True,
                )
            )

            obsolete_geiq_diagnoses.update(expires_at=timezone.localdate(self.created_at))

    def save(self, *args, **kwargs):
        self.clean()

        result = super().save(*args, **kwargs)

        # Invalidating obsolete ones *after* saving is ok
        self._invalidate_obsolete_geiq_diagnoses()

        return result

    @property
    def allowance_amount(self) -> int:
        # Only authorized prescribers may create a GEIQ diagnosis, so if the author is a prescriber
        # he was authorized when he created it
        return geiq_allowance_amount(self.author.is_prescriber, self.administrative_criteria.all())

    @property
    def author_structure(self):
        return self.author_geiq or self.author_prescriber_organization

    @classmethod
    def _expiration_date(cls, author=None):
        return timezone.localdate() + relativedelta(months=cls.EXPIRATION_DELAY_MONTHS)

    @classmethod
    @transaction.atomic()
    def create_eligibility_diagnosis(
        cls,
        job_seeker: User,
        author: User,
        author_structure: Company | PrescriberOrganization,
        administrative_criteria=(),
    ):
        author_org = author_geiq = author_kind = None

        if isinstance(author_structure, PrescriberOrganization):
            author_org = author_structure
            author_kind = AuthorKind.PRESCRIBER
        elif isinstance(author_structure, Company) and author_structure.kind == CompanyKind.GEIQ:
            if not administrative_criteria:
                raise ValueError("Un diagnostic effectué par un GEIQ doit avoir au moins un critère d'éligibilité")
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
            expires_at=cls._expiration_date(),
        )

        if administrative_criteria:
            result.administrative_criteria.set(administrative_criteria)
            if any([criterion.is_certifiable for criterion in administrative_criteria]):
                result.certify_criteria()

        # Sync GPS groups
        FollowUpGroup.objects.follow_beneficiary(job_seeker, author)

        return result

    @classmethod
    @transaction.atomic()
    def update_eligibility_diagnosis(cls, diagnosis, author: User, administrative_criteria):
        if not issubclass(diagnosis.__class__, cls):
            raise ValueError("Le diagnostic fourni n'est pas un diagnostic GEIQ")

        if not diagnosis.is_valid:
            raise ValueError("Impossible de modifier un diagnostic GEIQ expiré")

        diagnosis.author = author
        diagnosis.expires_at = timezone.localdate() + relativedelta(months=cls.EXPIRATION_DELAY_MONTHS)
        diagnosis.save()

        # Differences with IAE diagnosis model update:
        # - permission management is not handled by the model
        # - only administrative criteria are updatable
        diagnosis.administrative_criteria.set(administrative_criteria)
        if any([criterion.is_certifiable for criterion in administrative_criteria]):
            diagnosis.certify_criteria()

        return diagnosis


class GEIQAdministrativeCriteria(AbstractAdministrativeCriteria):
    parent = models.ForeignKey(
        "self",
        verbose_name="critère parent",
        blank=True,
        null=True,
        on_delete=models.RESTRICT,  # Prevent promoting a criteria from child to parent
    )
    # Some criteria do not belong to an annex or a level
    annex = models.CharField(
        verbose_name="annexe",
        max_length=3,
        choices=AdministrativeCriteriaAnnex.choices,
        default=AdministrativeCriteriaAnnex.ANNEX_1,
    )
    level = models.CharField(
        verbose_name="niveau",
        max_length=1,
        choices=AdministrativeCriteriaLevel.choices,
        # as opposed to IAE, level can be null (annex 1)
        null=True,
        blank=True,
    )
    slug = models.SlugField(verbose_name="référence courte", max_length=100, null=True, blank=True)
    # This represent the Label API codes of the matching criteria it can either be:
    #  - empty ("") meaning that this criteria is inexisting/irrelevant for Label
    #  - a single "CODE" for most cases
    #  - several "CODE1|CODE2" joined with a "|"
    api_code = models.CharField(verbose_name="code API")

    class Meta:
        verbose_name = "critère administratif GEIQ"
        verbose_name_plural = "critères administratifs GEIQ"
        ordering = [models.F("level").asc(nulls_last=True), "ui_rank"]
        constraints = [
            models.CheckConstraint(
                name="administrativecriteria_level_annex_consistency",
                violation_error_message="Incohérence entre l'annexe du critère administratif et son niveau",
                # Only criteria in Annex 2 (and hence those in both annexes) have a level
                condition=(
                    models.Q(
                        level__isnull=True,
                        annex__in=(AdministrativeCriteriaAnnex.NO_ANNEX, AdministrativeCriteriaAnnex.ANNEX_1),
                    )
                    | models.Q(
                        level__isnull=False,  # This condition is there to help Django's validate_constraints
                        level__in=(AdministrativeCriteriaLevel.LEVEL_1, AdministrativeCriteriaLevel.LEVEL_2),
                        annex__in=(AdministrativeCriteriaAnnex.ANNEX_2, AdministrativeCriteriaAnnex.BOTH_ANNEXES),
                    )
                ),
            ),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)

        return super().save(*args, **kwargs)

    @property
    def key(self):
        # For UI / forms
        return self.slug.replace("-", "_") if self.slug else ""


class GEIQSelectedAdministrativeCriteria(AbstractSelectedAdministrativeCriteria):
    eligibility_diagnosis = models.ForeignKey(
        GEIQEligibilityDiagnosis, on_delete=models.CASCADE, related_name="selected_administrative_criteria"
    )
    administrative_criteria = models.ForeignKey(
        GEIQAdministrativeCriteria,
        on_delete=models.RESTRICT,
        related_name="administrative_criteria_through",
    )

    class Meta:
        ordering = ["administrative_criteria"]
        verbose_name = "critère administratif GEIQ sélectionné"
        verbose_name_plural = "critères administratifs GEIQ sélectionnés"
        unique_together = ("eligibility_diagnosis", "administrative_criteria")

    def __str__(self):
        return str(self.pk)
