import logging

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.db import models, transaction
from django.db.models import Case, Exists, OuterRef, When
from django.utils import timezone

from itou.approvals.models import Approval
from itou.companies.models import CompanyMembership
from itou.eligibility.enums import AdministrativeCriteriaLevel, AuthorKind

from .common import (
    AbstractAdministrativeCriteria,
    AbstractEligibilityDiagnosisModel,
    AdministrativeCriteriaQuerySet,
    CommonEligibilityDiagnosisQuerySet,
)


logger = logging.getLogger(__name__)


class EligibilityDiagnosisQuerySet(CommonEligibilityDiagnosisQuerySet):
    def for_job_seeker_and_siae(self, viewing_user, job_seeker, *, siae=None):
        qs = self.filter(job_seeker=job_seeker)
        is_job_seeker_q = models.Q(job_seeker=viewing_user)
        # Prescriber diagnosis are viewable to all.
        author_q = models.Q(author_kind=AuthorKind.PRESCRIBER)
        if siae is not None:
            if (
                viewing_user.is_employer
                or viewing_user is None  # In Django admin, the viewing user does not matter and None is provided.
            ):
                siae_q = models.Q(author_siae=siae)
                if viewing_user.is_employer:
                    # SIAE make their own diagnosis for auto-prescriptions.
                    # Only viewable to members of that SIAE.
                    siae_q &= models.Q(
                        Exists(CompanyMembership.objects.active().filter(company=siae, user=viewing_user))
                    )
                author_q |= siae_q
            else:
                # foo
                pass
        return qs.filter(
            is_job_seeker_q  # Job seekers see all diagnoses about them.
            | ~is_job_seeker_q & author_q
        )

    def has_approval(self):
        """
        Annotate values with a boolean `_has_approval` attribute which can be
        filtered, e.g.:
        EligibilityDiagnosis.objects.has_approval().filter(_has_approval=True)
        """
        has_approval = Approval.objects.filter(user=OuterRef("job_seeker")).valid()
        return self.annotate(_has_approval=Exists(has_approval))


class EligibilityDiagnosisManager(models.Manager):
    def has_considered_valid(self, viewing_user, job_seeker, for_siae=None):
        """
        Returns True if the given job seeker has a considered valid diagnosis,
        False otherwise.

        We consider the eligibility as valid when a PASS IAE is valid but
        the eligibility diagnosis is missing.

        This can happen when we have to:
        - import approvals previously issued by Pôle emploi
        - create PASS IAE manually for AI (16K+)
        - etc.

        In these cases, the diagnoses have been made outside of Itou.

        Hence the Trello #2604 decision: if a PASS IAE is valid, we do not
        check the presence of an eligibility diagnosis.
        """
        return job_seeker.has_valid_common_approval or bool(
            self.last_considered_valid(viewing_user, job_seeker, for_siae=for_siae)
        )

    def last_considered_valid(self, viewing_user, job_seeker, for_siae=None):
        """
        Retrieves the given job seeker's last considered valid diagnosis or None.

        If the `for_siae` argument is passed and we are looking for a diagnosis
        from an employer perspective. The scope is restricted to avoid showing
        diagnoses made by employers to other employers and prescribers.

        A diagnosis made by a prescriber takes precedence even when an employer
        diagnosis already exists.
        """

        query = (
            self.for_job_seeker_and_siae(viewing_user, job_seeker, siae=for_siae)
            .select_related("author", "author_siae", "author_prescriber_organization")
            .annotate(from_prescriber=Case(When(author_kind=AuthorKind.PRESCRIBER, then=1), default=0))
            .order_by("-from_prescriber", "-created_at")
        )
        if not job_seeker.has_valid_common_approval:
            query = query.valid()
        # Otherwise, a diagnosis is considered valid for the duration of an
        # approval, we just retrieve the last one no matter if it's valid or
        # not.
        return query.first()

    def last_expired(self, viewing_user, job_seeker, for_siae=None):
        """
        Retrieves the given job seeker's last expired diagnosis or None.

        Return None if last diagnosis is considered valid.
        """

        last = None
        query = (
            self.expired()
            .select_related("author", "author_siae", "author_prescriber_organization")
            .order_by("created_at")
        )

        if not self.has_considered_valid(viewing_user, job_seeker, for_siae=for_siae):
            last = query.for_job_seeker_and_siae(viewing_user, job_seeker, siae=for_siae).last()

        return last


class EligibilityDiagnosis(AbstractEligibilityDiagnosisModel):
    """
    Store the eligibility diagnosis (IAE) of a job seeker.
    """

    # Not in abstract model to avoid 'related_name' clashing (and ugly auto-naming)
    job_seeker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="demandeur d'emploi",
        on_delete=models.CASCADE,
        related_name="eligibility_diagnoses",
    )
    # When the author is an SIAE member, keep a track of his current SIAE.
    author_siae = models.ForeignKey(
        "companies.Company",
        verbose_name="SIAE de l'auteur",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    # Administrative criteria are mandatory only when an SIAE is performing an eligibility diagnosis.
    administrative_criteria = models.ManyToManyField(
        "eligibility.AdministrativeCriteria",
        verbose_name="critères administratifs",
        through="SelectedAdministrativeCriteria",
        blank=True,
    )

    objects = EligibilityDiagnosisManager.from_queryset(EligibilityDiagnosisQuerySet)()

    class Meta:
        verbose_name = "diagnostic d'éligibilité IAE"
        verbose_name_plural = "diagnostics d'éligibilité IAE"
        ordering = ["-created_at"]

    @property
    def author_organization(self):
        return self.author_prescriber_organization or self.author_siae

    # A diagnosis is considered valid for the whole duration of an approval.
    # Methods below (whose name contain `considered`) take into account
    # the existence of an ongoing approval.
    # They must not be used "as-is" in admin's `list_display` because checking
    # the latest approvals would trigger additional SQL queries for each row.

    @property
    def is_considered_valid(self):
        return self.is_valid or self.job_seeker.has_valid_common_approval

    @property
    def considered_to_expire_at(self):
        if self.job_seeker.has_valid_common_approval:
            return self.job_seeker.latest_common_approval.end_at
        return self.expires_at

    @classmethod
    @transaction.atomic()
    def create_diagnosis(cls, job_seeker, *, author, author_organization, administrative_criteria=None):
        """
        Arguments:
            job_seeker: User() object
        Keyword arguments:
            author: User() object, future diagnosis author
            author_organization: either Siae, PrescriberOrganization or None, future diagnosis author organization
            administrative_criteria: an optional list of AdministrativeCriteria() objects
        """
        diagnosis = cls.objects.create(
            job_seeker=job_seeker,
            author=author,
            author_kind=author.kind,
            author_siae=author_organization if author.is_employer else None,
            author_prescriber_organization=author_organization if author.is_prescriber else None,
        )
        if administrative_criteria:
            diagnosis.administrative_criteria.add(*administrative_criteria)
        return diagnosis

    @classmethod
    @transaction.atomic()
    def update_diagnosis(cls, eligibility_diagnosis, *, author, author_organization, administrative_criteria):
        # If we have the same author and the same criteria then extend the life of the current one
        extend_conditions = [
            eligibility_diagnosis.author == author,
            set(eligibility_diagnosis.administrative_criteria.all()) == set(administrative_criteria),
        ]
        if all(extend_conditions):
            eligibility_diagnosis.expires_at = timezone.now() + relativedelta(
                months=EligibilityDiagnosis.EXPIRATION_DELAY_MONTHS
            )
            eligibility_diagnosis.save(update_fields=["expires_at"])
            return eligibility_diagnosis

        # Otherwise, we create a new one...
        new_eligibility_diagnosis = cls.create_diagnosis(
            eligibility_diagnosis.job_seeker,
            author=author,
            author_organization=author_organization,
            administrative_criteria=administrative_criteria,
        )
        # and mark the current one as expired
        eligibility_diagnosis.expires_at = new_eligibility_diagnosis.created_at
        eligibility_diagnosis.save(update_fields=["expires_at"])
        return new_eligibility_diagnosis


class AdministrativeCriteria(AbstractAdministrativeCriteria):
    """
    List of administrative criteria.
    They can be created and updated using the admin.

    The table is automatically populated with a fixture at the end of
    eligibility's migration #0007.

    Warning : any change to the criteria must be notified to C2 members (names are used in Metabase)
    """

    MAX_UI_RANK = 32767

    level = models.CharField(
        verbose_name="niveau",
        max_length=1,
        choices=AdministrativeCriteriaLevel.choices,
        default=AdministrativeCriteriaLevel.LEVEL_1,
    )

    name = models.CharField(verbose_name="nom", max_length=255)
    desc = models.CharField(verbose_name="description", max_length=255, blank=True)
    written_proof = models.CharField(verbose_name="justificatif", max_length=255, blank=True)
    written_proof_url = models.URLField(
        verbose_name="lien d'aide à propos du justificatif", max_length=200, blank=True
    )
    written_proof_validity = models.CharField(
        verbose_name="durée de validité du justificatif", max_length=255, blank=True, default=""
    )
    # Used to rank criteria in UI. Should be set by level (LEVEL_1: 1, 2, 3… LEVEL_2: 1, 2, 3…).
    # Default value is MAX_UI_RANK so that it's pushed at the end if `ui_rank` is forgotten.
    ui_rank = models.PositiveSmallIntegerField(default=MAX_UI_RANK)
    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="créé par", null=True, blank=True, on_delete=models.SET_NULL
    )

    objects = AdministrativeCriteriaQuerySet.as_manager()

    class Meta:
        verbose_name = "critère administratif IAE"
        verbose_name_plural = "critères administratifs IAE"
        ordering = ["level", "ui_rank"]

    @property
    def key(self):
        return f"level_{self.level}_{self.pk}"


class SelectedAdministrativeCriteria(models.Model):
    """
    Selected administrative criteria of an eligibility diagnosis.
    Intermediary model between `EligibilityDiagnosis` and `AdministrativeCriteria`.
    https://docs.djangoproject.com/en/dev/ref/models/relations/
    """

    eligibility_diagnosis = models.ForeignKey(EligibilityDiagnosis, on_delete=models.CASCADE)
    administrative_criteria = models.ForeignKey(
        AdministrativeCriteria,
        on_delete=models.CASCADE,
        related_name="administrative_criteria_through",
    )
    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now)

    class Meta:
        verbose_name = "critère administratif IAE sélectionné"
        verbose_name_plural = "critères administratifs IAE sélectionnés"
        unique_together = ("eligibility_diagnosis", "administrative_criteria")

    def __str__(self):
        return f"{self.pk}"
