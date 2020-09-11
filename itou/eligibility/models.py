import logging

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

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


class EligibilityDiagnosisManager(models.Manager):
    def has_valid_from_pole_emploi(self, job_seeker):
        """
        Returns True if the given job seeker has a valid diagnosis made outside
        of Itou, False otherwise.

        The existence of a valid Pôle emploi's approval implies that a
        diagnosis has been made outside of Itou.
        """
        latest_approval = job_seeker.approvals_wrapper.latest_approval
        return bool(latest_approval and latest_approval.is_valid and not latest_approval.originates_from_itou)

    def has_valid(self, job_seeker, for_siae=None):
        """
        Returns True if the given job seeker has a valid diagnosis, False otherwise.
        """
        return self.has_valid_from_pole_emploi(job_seeker) or bool(self.last_valid(job_seeker, for_siae=for_siae))

    def last_valid(self, job_seeker, for_siae=None):
        """
        Retrieves the last valid diagnosis for the given job seeker, if any.

        A diagnosis made by a prescriber takes precedence.

        If the `for_siae` argument is passed, it means that we are looking for
        a diagnosis from an employer perspective. The scope is restricted to
        avoid showing diagnoses made by other employers.
        """

        last = None
        query = (
            self.filter(job_seeker=job_seeker)
            .select_related("author", "author_siae", "author_prescriber_organization")
            .order_by("created_at")
        )

        # The last diagnosis is considered valid for the duration of an approval.
        if job_seeker.approvals_wrapper.has_valid:
            last = query.filter(author_kind=self.model.AUTHOR_KIND_PRESCRIBER).last()
            if not last:
                last = query.filter(author_siae=for_siae).last()
            if not last:
                # Deals with cases from the past (when there was no restriction).
                last = query.last()

        else:
            last = query.valid().filter(author_kind=self.model.AUTHOR_KIND_PRESCRIBER).last()
            if not last and for_siae:
                last = query.valid().filter(author_siae=for_siae).last()

        return last


class EligibilityDiagnosis(models.Model):
    """
    Store the eligibility diagnosis of a job seeker.
    """

    AUTHOR_KIND_PRESCRIBER = KIND_PRESCRIBER
    AUTHOR_KIND_SIAE_STAFF = KIND_SIAE_STAFF

    AUTHOR_KIND_CHOICES = (
        (AUTHOR_KIND_PRESCRIBER, _("Prescripteur")),
        (AUTHOR_KIND_SIAE_STAFF, _("Employeur (SIAE)")),
    )

    EXPIRATION_DELAY_MONTHS = 6

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
    # Administrative criteria are mandatory only when an SIAE is performing an eligibility diagnosis.
    administrative_criteria = models.ManyToManyField(
        "eligibility.AdministrativeCriteria",
        verbose_name=_("Critères administratifs"),
        through="SelectedAdministrativeCriteria",
        blank=True,
    )

    created_at = models.DateTimeField(verbose_name=_("Date de création"), default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(verbose_name=_("Date de modification"), blank=True, null=True, db_index=True)

    objects = EligibilityDiagnosisManager.from_queryset(EligibilityDiagnosisQuerySet)()

    class Meta:
        verbose_name = _("Diagnostic d'éligibilité")
        verbose_name_plural = _("Diagnostics d'éligibilité")
        ordering = ["-created_at"]

    def __str__(self):
        return str(self.id)

    @property
    def is_valid(self):
        return self.created_at > self.get_expiration_dt()

    @property
    def is_considered_valid(self):
        return self.job_seeker.approvals_wrapper.has_valid

    @property
    def has_expired(self):
        return not self.is_valid

    @property
    def expires_at(self):
        return self.created_at + relativedelta(months=self.EXPIRATION_DELAY_MONTHS)

    def save(self, *args, **kwargs):
        self.updated_at = timezone.now()
        return super().save(*args, **kwargs)

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
        LEVEL_1 = "1", _("Niveau 1")
        LEVEL_2 = "2", _("Niveau 2")

    level = models.CharField(verbose_name=_("Niveau"), max_length=1, choices=Level.choices, default=Level.LEVEL_1)
    name = models.CharField(verbose_name=_("Nom"), max_length=255)
    desc = models.CharField(verbose_name=_("Description"), max_length=255, blank=True)
    written_proof = models.CharField(verbose_name=_("Justificatif"), max_length=255, blank=True)
    written_proof_url = models.URLField(
        verbose_name=_("Lien d'aide à propos du justificatif"), max_length=200, blank=True
    )
    # Used to rank criteria in UI. Should be set by level (LEVEL_1: 1, 2, 3… LEVEL_2: 1, 2, 3…).
    # Default value is MAX_UI_RANK so that it's pushed at the end if `ui_rank` is forgotten.
    ui_rank = models.PositiveSmallIntegerField(default=MAX_UI_RANK)
    created_at = models.DateTimeField(verbose_name=_("Date de création"), default=timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name=_("Créé par"), null=True, blank=True, on_delete=models.SET_NULL
    )

    objects = models.Manager.from_queryset(AdministrativeCriteriaQuerySet)()

    class Meta:
        verbose_name = _("Critère administratif")
        verbose_name_plural = _("Critères administratifs")
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
    created_at = models.DateTimeField(verbose_name=_("Date de création"), default=timezone.now)

    class Meta:
        verbose_name = _("Critère administratif sélectionné")
        verbose_name_plural = _("Critères administratifs sélectionnés")
        unique_together = ("eligibility_diagnosis", "administrative_criteria")

    def __str__(self):
        return f"{self.id}"
