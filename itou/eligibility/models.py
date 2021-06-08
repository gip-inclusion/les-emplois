import datetime
import logging

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.db import models
from django.db.models import Exists, OuterRef
from django.utils import timezone

from itou.approvals.models import Approval
from itou.utils.perms.user import KIND_PRESCRIBER, KIND_SIAE_STAFF


logger = logging.getLogger(__name__)


class EligibilityDiagnosisQuerySet(models.QuerySet):
    @property
    def valid_lookup(self):
        return models.Q(created_at__gt=self.model.get_expiration_dt())

    def valid(self):
        return self.filter(self.valid_lookup)

    def expired(self):
        return self.exclude(self.valid_lookup)

    def authored_by_siae(self, for_siae):
        return self.filter(author_siae=for_siae)

    def before(self, before):
        if isinstance(before, datetime.date):
            return self.filter(created_at__date__lt=before)
        return self.filter(created_at__lt=before)

    def by_author_kind_prescriber(self):
        return self.filter(author_kind=self.model.AUTHOR_KIND_PRESCRIBER)

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
        Returns True if the given job seeker has a considered valid diagnosis, False otherwise.
        """
        return job_seeker.approvals_wrapper.has_valid_pole_emploi_eligibility_diagnosis or bool(
            self.last_considered_valid(job_seeker, for_siae=for_siae)
        )

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
        if job_seeker.approvals_wrapper and job_seeker.approvals_wrapper.has_valid:
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

    def last_before(self, job_seeker, before, for_siae=None):
        """
        Retrieves the given job seeker's last diagnosis (valid or expired)
        before the given date or None.

        If the `for_siae` argument is passed, it means that we are looking for
        a diagnosis from an employer perspective. The scope is restricted to
        avoid showing diagnoses made by other employers.

        A diagnosis made by a prescriber takes precedence even when an employer
        diagnosis already exists.
        """

        last = None
        query = self.for_job_seeker(job_seeker).before(before).order_by("created_at")

        last = query.by_author_kind_prescriber().last()
        if not last and for_siae:
            last = query.authored_by_siae(for_siae).last()

        return last


class EligibilityDiagnosis(models.Model):
    """
    Store the eligibility diagnosis of a job seeker.
    """

    AUTHOR_KIND_PRESCRIBER = KIND_PRESCRIBER
    AUTHOR_KIND_SIAE_STAFF = KIND_SIAE_STAFF

    AUTHOR_KIND_CHOICES = (
        (AUTHOR_KIND_PRESCRIBER, "Prescripteur"),
        (AUTHOR_KIND_SIAE_STAFF, "Employeur (SIAE)"),
    )

    EXPIRATION_DELAY_MONTHS = 6

    job_seeker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Demandeur d'emploi",
        on_delete=models.CASCADE,
        related_name="eligibility_diagnoses",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Auteur",
        on_delete=models.CASCADE,
        related_name="eligibility_diagnoses_made",
    )
    author_kind = models.CharField(
        verbose_name="Type de l'auteur", max_length=10, choices=AUTHOR_KIND_CHOICES, default=AUTHOR_KIND_PRESCRIBER
    )
    # When the author is an SIAE staff member, keep a track of his current SIAE.
    author_siae = models.ForeignKey(
        "siaes.Siae", verbose_name="SIAE de l'auteur", null=True, blank=True, on_delete=models.CASCADE
    )
    # When the author is a prescriber, keep a track of his current organization.
    author_prescriber_organization = models.ForeignKey(
        "prescribers.PrescriberOrganization",
        verbose_name="Organisation du prescripteur de l'auteur",
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

    created_at = models.DateTimeField(verbose_name="Date de création", default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(verbose_name="Date de modification", blank=True, null=True, db_index=True)

    objects = EligibilityDiagnosisManager.from_queryset(EligibilityDiagnosisQuerySet)()

    class Meta:
        verbose_name = "Diagnostic d'éligibilité"
        verbose_name_plural = "Diagnostics d'éligibilité"
        ordering = ["-created_at"]

    def __str__(self):
        return str(self.id)

    def save(self, *args, **kwargs):
        self.updated_at = timezone.now()
        return super().save(*args, **kwargs)

    @property
    def is_valid(self):
        return self.created_at > self.get_expiration_dt()

    @property
    def expires_at(self):
        return self.created_at + relativedelta(months=self.EXPIRATION_DELAY_MONTHS)

    # A diagnosis is considered valid for the whole duration of an approval.
    # Methods below (whose name contain `considered`) take into account
    # the existence of an ongoing approval.
    # They must not be used "as-is" in admin's `list_display` because checking
    # approvals_wrapper would trigger additional SQL queries for each row.

    @property
    def is_considered_valid(self):
        return self.is_valid or self.job_seeker.approvals_wrapper.has_valid

    @property
    def considered_to_expire_at(self):
        if self.job_seeker.approvals_wrapper.has_valid:
            return self.job_seeker.approvals_wrapper.latest_approval.extended_end_at
        return self.expires_at

    @classmethod
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
            for criteria in administrative_criteria:
                diagnosis.administrative_criteria.add(criteria)
            diagnosis.save()
        return diagnosis

    @staticmethod
    def get_expiration_dt():
        # Everything created after this date is valid.
        return timezone.now() - relativedelta(months=EligibilityDiagnosis.EXPIRATION_DELAY_MONTHS)


class AdministrativeCriteriaQuerySet(models.QuerySet):
    def level1(self):
        return self.filter(level=AdministrativeCriteria.Level.LEVEL_1)

    def level2(self):
        return self.filter(level=AdministrativeCriteria.Level.LEVEL_2)


class AdministrativeCriteria(models.Model):
    """
    List of administrative criteria.
    They can be created and updated using the admin.

    The table is automatically populated with a fixture at the end of
    eligibility's migration #0003.
    """

    MAX_UI_RANK = 32767

    class Level(models.TextChoices):
        LEVEL_1 = "1", "Niveau 1"
        LEVEL_2 = "2", "Niveau 2"

    level = models.CharField(verbose_name="Niveau", max_length=1, choices=Level.choices, default=Level.LEVEL_1)
    name = models.CharField(verbose_name="Nom", max_length=255)
    desc = models.CharField(verbose_name="Description", max_length=255, blank=True)
    written_proof = models.CharField(verbose_name="Justificatif", max_length=255, blank=True)
    written_proof_url = models.URLField(
        verbose_name="Lien d'aide à propos du justificatif", max_length=200, blank=True
    )
    # Used to rank criteria in UI. Should be set by level (LEVEL_1: 1, 2, 3… LEVEL_2: 1, 2, 3…).
    # Default value is MAX_UI_RANK so that it's pushed at the end if `ui_rank` is forgotten.
    ui_rank = models.PositiveSmallIntegerField(default=MAX_UI_RANK)
    created_at = models.DateTimeField(verbose_name="Date de création", default=timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Créé par", null=True, blank=True, on_delete=models.SET_NULL
    )

    objects = models.Manager.from_queryset(AdministrativeCriteriaQuerySet)()

    class Meta:
        verbose_name = "Critère administratif"
        verbose_name_plural = "Critères administratifs"
        ordering = ["level", "ui_rank"]

    def __str__(self):
        return f"{self.name} - {self.get_level_display()}"


class SelectedAdministrativeCriteria(models.Model):
    """
    Selected administrative criteria of an eligibility diagnosis.
    Intermediary model between `EligibilityDiagnosis` and `AdministrativeCriteria`.
    https://docs.djangoproject.com/en/dev/ref/models/relations/
    """

    eligibility_diagnosis = models.ForeignKey(EligibilityDiagnosis, on_delete=models.CASCADE)
    administrative_criteria = models.ForeignKey(
        AdministrativeCriteria, on_delete=models.CASCADE, related_name="administrative_criteria_through"
    )
    created_at = models.DateTimeField(verbose_name="Date de création", default=timezone.now)

    class Meta:
        verbose_name = "Critère administratif sélectionné"
        verbose_name_plural = "Critères administratifs sélectionnés"
        unique_together = ("eligibility_diagnosis", "administrative_criteria")

    def __str__(self):
        return f"{self.id}"
