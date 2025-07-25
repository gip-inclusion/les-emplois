import datetime
import logging

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.db import models, transaction
from django.db.models import Case, Exists, OuterRef, Q, When
from django.utils import timezone

from itou.approvals.models import Approval
from itou.companies.enums import CompanyKind
from itou.eligibility.enums import AuthorKind
from itou.eligibility.models.common import (
    AbstractAdministrativeCriteria,
    AbstractEligibilityDiagnosisModel,
    AbstractSelectedAdministrativeCriteria,
    CommonEligibilityDiagnosisQuerySet,
)
from itou.gps.models import FollowUpGroup


logger = logging.getLogger(__name__)


class EligibilityDiagnosisQuerySet(CommonEligibilityDiagnosisQuerySet):
    def for_job_seeker_and_siae(self, job_seeker, *, siae=None):
        author_filter = models.Q(author_kind=AuthorKind.PRESCRIBER)
        if siae is not None:
            author_filter |= models.Q(author_siae=siae)
        return self.filter(author_filter, job_seeker=job_seeker)

    def has_approval(self):
        """
        Annotate values with a boolean `_has_approval` attribute which can be
        filtered, e.g.:
        EligibilityDiagnosis.objects.has_approval().filter(_has_approval=True)
        """
        has_approval = Approval.objects.filter(user=OuterRef("job_seeker")).valid()
        return self.annotate(_has_approval=Exists(has_approval))


class EligibilityDiagnosisManager(models.Manager):
    def has_considered_valid(self, job_seeker, for_siae=None):
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
        return job_seeker.has_valid_approval or bool(self.last_considered_valid(job_seeker, for_siae=for_siae))

    def last_considered_valid(self, job_seeker, for_siae=None, prefetch=None):
        """
        Retrieves the given job seeker's last considered valid diagnosis or None.

        If the `for_siae` argument is passed, it means that we are looking for
        a diagnosis from an employer perspective. The scope is restricted to
        avoid showing diagnoses made by other employers.

        A diagnosis made by a prescriber takes precedence even when an employer
        diagnosis already exists.
        """

        query = (
            self.for_job_seeker_and_siae(job_seeker, siae=for_siae)
            .select_related("author", "author_siae", "author_prescriber_organization")
            .annotate(from_prescriber=Case(When(author_kind=AuthorKind.PRESCRIBER, then=1), default=0))
            .order_by("-from_prescriber", "-created_at")
        )

        if prefetch:
            query = query.prefetch_related(*prefetch)

        if not job_seeker.has_valid_approval:
            query = query.valid()
        # Otherwise, a diagnosis is considered valid for the duration of an
        # approval, we just retrieve the last one no matter if it's valid or
        # not.
        return query.first()

    def last_expired(self, job_seeker, for_siae=None):
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

        if not self.has_considered_valid(job_seeker=job_seeker, for_siae=for_siae):
            last = query.for_job_seeker_and_siae(job_seeker, siae=for_siae).last()

        return last

    def last_for_job_seeker(self, job_seeker):
        """
        Retrieves the given job seeker eligibility diagnosis from his perpective:
          - a valid diagnosis (considered valid even if expired, if an approval is ongoing),
        either from an authorized prescriber or from an employer, if the diagnosis leads
        to an approval
          - an expired diagnosis if there is no valid diagnoses but an expired one
        """

        approval_subquery = Exists(Approval.objects.filter(eligibility_diagnosis=OuterRef("pk")))
        query = (
            self.filter(job_seeker=job_seeker)
            .prefetch_related("approval_set")
            .annotate(with_approval=approval_subquery)
            .annotate(from_prescriber=Case(When(author_kind=AuthorKind.PRESCRIBER, then=1), default=0))
            .filter(Q(with_approval=True) | Q(author_kind=AuthorKind.PRESCRIBER))
            .order_by("-from_prescriber", "-created_at")
            .prefetch_related("selected_administrative_criteria__administrative_criteria")
            .select_related("author", "author_siae", "author_prescriber_organization", "job_seeker")
        )

        return query.first()


class EligibilityDiagnosis(AbstractEligibilityDiagnosisModel):
    """
    Store the eligibility diagnosis (IAE) of a job seeker.
    """

    EMPLOYER_DIAGNOSIS_VALIDITY_TIMEDELTA = datetime.timedelta(days=92)

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
        limit_choices_to={"kind__in": CompanyKind.siae_kinds()},
        on_delete=models.RESTRICT,  # For traceability and accountability
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
        constraints = [
            models.CheckConstraint(
                name="eligibility_iae_diagnosis_author_kind_coherence",
                violation_error_message="La structure de l'auteur ne correspond pas à son type",
                condition=models.Q(
                    author_kind=AuthorKind.EMPLOYER,
                    author_siae__isnull=False,
                    author_prescriber_organization__isnull=True,
                )
                | models.Q(
                    author_kind=AuthorKind.PRESCRIBER,
                    author_prescriber_organization__isnull=False,
                    author_siae__isnull=True,
                ),
            ),
        ]

    @property
    def author_organization(self):
        return self.author_prescriber_organization or self.author_siae

    # A diagnosis is considered valid for the whole duration of an approval.
    # Methods below (whose name contain `considered`) take into account
    # the existence of an ongoing approval associated to the diagnosis.
    # There should be 0 or 1 associated approval, but for a handful of diagnoses
    # there are 2, so we pick the last one.
    # They must not be used "as-is" in admin's `list_display` because checking
    # the latest approvals would trigger additional SQL queries for each row.

    @property
    def is_considered_valid(self):
        valid_approvals = self.approval_set.filter(end_at__gt=timezone.localdate())
        return self.is_valid or valid_approvals.exists()

    @property
    def considered_to_expire_at(self):
        latest_approval = self.approval_set.last()
        if latest_approval and latest_approval.is_valid():
            return latest_approval.end_at
        return self.expires_at

    @classmethod
    def _expiration_date(cls, author):
        now = timezone.localdate()
        if author.is_employer:
            # For siae_evaluations, employers must provide a proof for administrative criteria
            # supporting the hire. A proof is valid for 3 months, align employer diagnosis
            # duration with proof validity duration.
            return now + cls.EMPLOYER_DIAGNOSIS_VALIDITY_TIMEDELTA
        return now + relativedelta(months=cls.EXPIRATION_DELAY_MONTHS)

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
            expires_at=cls._expiration_date(author),
        )
        if administrative_criteria:
            diagnosis.administrative_criteria.add(*administrative_criteria)
            if any([criterion.is_certifiable for criterion in administrative_criteria]):
                diagnosis.certify_criteria()

        # Sync GPS groups
        FollowUpGroup.objects.follow_beneficiary(job_seeker, author)

        return diagnosis

    @classmethod
    @transaction.atomic()
    def update_diagnosis(cls, eligibility_diagnosis, *, author, author_organization, administrative_criteria):
        # Create a new diagnostic to be aligned with the criteria certification period.
        new_eligibility_diagnosis = cls.create_diagnosis(
            eligibility_diagnosis.job_seeker,
            author=author,
            author_organization=author_organization,
            administrative_criteria=administrative_criteria,
        )
        # And mark the current one as expired.
        eligibility_diagnosis.expires_at = timezone.localdate(new_eligibility_diagnosis.created_at)
        eligibility_diagnosis.save(update_fields=["expires_at", "updated_at"])
        return new_eligibility_diagnosis


class AdministrativeCriteria(AbstractAdministrativeCriteria):
    """
    List of administrative criteria.
    They can be created and updated using the admin.

    The table is automatically populated.
    See itou.eligibility.apps::create_administrative_criteria

    Warning : any change to the criteria must be notified to C2 members (names are used in Metabase)
    """

    class Meta:
        verbose_name = "critère administratif IAE"
        verbose_name_plural = "critères administratifs IAE"
        ordering = ["level", "ui_rank"]

    @property
    def key(self):
        return f"level_{self.level}_{self.pk}"


class SelectedAdministrativeCriteria(AbstractSelectedAdministrativeCriteria):
    """
    Selected administrative criteria of an eligibility diagnosis.
    Intermediary model between `EligibilityDiagnosis` and `AdministrativeCriteria`.
    https://docs.djangoproject.com/en/dev/ref/models/relations/
    """

    eligibility_diagnosis = models.ForeignKey(
        EligibilityDiagnosis, on_delete=models.CASCADE, related_name="selected_administrative_criteria"
    )
    administrative_criteria = models.ForeignKey(
        AdministrativeCriteria,
        on_delete=models.RESTRICT,
        related_name="administrative_criteria_through",
    )

    class Meta:
        ordering = ["administrative_criteria"]
        verbose_name = "critère administratif IAE sélectionné"
        verbose_name_plural = "critères administratifs IAE sélectionnés"
        unique_together = ("eligibility_diagnosis", "administrative_criteria")

    def __str__(self):
        return f"{self.pk}"
