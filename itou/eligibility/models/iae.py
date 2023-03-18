import logging

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.db import models, transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

from itou.approvals.models import Approval
from itou.eligibility.enums import AdministrativeCriteriaLevel, AuthorKind

from .common import (
    AbstractAdministrativeCriteria,
    AbstractEligibilityDiagnosisModel,
    AdministrativeCriteriaQuerySet,
    CommonEligibilityDiagnosisQuerySet,
)


logger = logging.getLogger(__name__)


class EligibilityDiagnosisQuerySet(CommonEligibilityDiagnosisQuerySet):
    def authored_by_siae(self, for_siae):
        return self.filter(author_siae=for_siae)

    def by_author_kind_prescriber_or_siae(self, for_siae):
        return self.filter(models.Q(author_kind=AuthorKind.PRESCRIBER) | models.Q(author_siae=for_siae))

    def for_job_seeker(self, job_seeker):
        return self.filter(job_seeker=job_seeker).select_related(
            "author", "author_siae", "author_prescriber_organization"
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
        return job_seeker.has_valid_common_approval or bool(self.last_considered_valid(job_seeker, for_siae=for_siae))

    def last_considered_valid(self, job_seeker, for_siae=None):
        """
        Retrieves the given job seeker's last considered valid diagnosis or None.

        If the `for_siae` argument is passed, it means that we are looking for
        a diagnosis from an employer perspective. The scope is restricted to
        avoid showing diagnoses made by other employers.

        A diagnosis made by a prescriber takes precedence even when an employer
        diagnosis already exists.
        """

        last = None
        query = self.for_job_seeker(job_seeker).order_by("created_at")

        # A diagnosis is considered valid for the duration of an approval,
        # we just retrieve the last one no matter if it's valid or not.
        if job_seeker.has_valid_common_approval:
            last = query.by_author_kind_prescriber().last()
            if not last and for_siae:
                last = query.authored_by_siae(for_siae).last()
            if not last:
                # Deals with cases from the past (when there was no restriction).
                last = query.last()

        # Otherwise, search only in "non expired" diagnosis.
        else:
            last = query.valid().by_author_kind_prescriber().last()
            if not last and for_siae:
                last = query.valid().authored_by_siae(for_siae).last()

        return last

    def last_expired(self, job_seeker, for_siae=None):
        """
        Retrieves the given job seeker's last expired diagnosis or None.

        Return None if last diagnosis is considered valid.
        """

        last = None
        query = self.for_job_seeker(job_seeker).order_by("created_at")

        # check if no diagnosis has considered valid
        if not self.has_considered_valid(job_seeker=job_seeker, for_siae=for_siae):
            if for_siae:
                # get the last one made by this siae or a prescriber
                last = query.expired().by_author_kind_prescriber_or_siae(for_siae=for_siae).last()
            else:
                # get the last one no matter who did it
                last = query.expired().last()

        return last


class EligibilityDiagnosis(AbstractEligibilityDiagnosisModel):
    """
    Store the eligibility diagnosis (IAE) of a job seeker.
    """

    # Not in abstract model to avoid 'related_name' clashing (and ugly auto-naming)
    job_seeker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Demandeur d'emploi",
        on_delete=models.CASCADE,
        related_name="eligibility_diagnoses",
    )
    # When the author is an SIAE staff member, keep a track of his current SIAE.
    author_siae = models.ForeignKey(
        "siaes.Siae",
        verbose_name="SIAE de l'auteur",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    # Administrative criteria are mandatory only when an SIAE is performing an eligibility diagnosis.
    administrative_criteria = models.ManyToManyField(
        "eligibility.AdministrativeCriteria",
        verbose_name="Critères administratifs",
        through="SelectedAdministrativeCriteria",
        blank=True,
    )

    objects = EligibilityDiagnosisManager.from_queryset(EligibilityDiagnosisQuerySet)()

    class Meta:
        verbose_name = "Diagnostic d'éligibilité IAE"
        verbose_name_plural = "Diagnostics d'éligibilité IAE"
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
    def create_diagnosis(cls, job_seeker, user_info, administrative_criteria=None):
        """
        Arguments:
            job_seeker: User() object
            user_info: UserInfo namedtuple (itou.utils.perms.user.get_user_info)
        Keyword arguments:
            administrative_criteria: an optional list of AdministrativeCriteria() objects
        """
        diagnosis = cls.objects.create(
            job_seeker=job_seeker,
            author=user_info.user,
            author_kind=user_info.kind,
            author_siae=user_info.siae,
            author_prescriber_organization=user_info.prescriber_organization,
        )
        if administrative_criteria:
            diagnosis.administrative_criteria.add(*administrative_criteria)
        return diagnosis

    @classmethod
    @transaction.atomic()
    def update_diagnosis(cls, eligibility_diagnosis, user_info, administrative_criteria):
        # If we have the same author and the same criteria then extend the life of the current one
        extend_conditions = [
            eligibility_diagnosis.author == user_info.user,
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
            eligibility_diagnosis.job_seeker, user_info, administrative_criteria
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
        verbose_name="Niveau",
        max_length=1,
        choices=AdministrativeCriteriaLevel.choices,
        default=AdministrativeCriteriaLevel.LEVEL_1,
    )

    name = models.CharField(verbose_name="Nom", max_length=255)
    desc = models.CharField(verbose_name="Description", max_length=255, blank=True)
    written_proof = models.CharField(verbose_name="Justificatif", max_length=255, blank=True)
    written_proof_url = models.URLField(
        verbose_name="Lien d'aide à propos du justificatif", max_length=200, blank=True
    )
    written_proof_validity = models.CharField(
        verbose_name="Durée de validité du justificatif", max_length=255, blank=True, default=""
    )
    # Used to rank criteria in UI. Should be set by level (LEVEL_1: 1, 2, 3… LEVEL_2: 1, 2, 3…).
    # Default value is MAX_UI_RANK so that it's pushed at the end if `ui_rank` is forgotten.
    ui_rank = models.PositiveSmallIntegerField(default=MAX_UI_RANK)
    created_at = models.DateTimeField(verbose_name="Date de création", default=timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Créé par", null=True, blank=True, on_delete=models.SET_NULL
    )

    objects = AdministrativeCriteriaQuerySet.as_manager()

    class Meta:
        verbose_name = "Critère administratif IAE"
        verbose_name_plural = "Critères administratifs IAE"
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
    created_at = models.DateTimeField(verbose_name="Date de création", default=timezone.now)

    class Meta:
        verbose_name = "Critère administratif IAE sélectionné"
        verbose_name_plural = "Critères administratifs IAE sélectionnés"
        unique_together = ("eligibility_diagnosis", "administrative_criteria")

    def __str__(self):
        return f"{self.pk}"
