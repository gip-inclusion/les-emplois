import datetime

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.db import models
from django.utils import timezone

from itou.eligibility.enums import AdministrativeCriteriaLevel, AuthorKind


class CommonEligibilityDiagnosisQuerySet(models.QuerySet):
    def valid(self):
        return self.filter(expires_at__gt=timezone.now())

    def expired(self):
        return self.filter(expires_at__lte=timezone.now())

    def before(self, before):
        if isinstance(before, datetime.date):
            return self.filter(created_at__date__lt=before)
        return self.filter(created_at__lt=before)

    def by_author_kind_prescriber(self):
        return self.filter(author_kind=AuthorKind.PRESCRIBER)


class AbstractEligibilityDiagnosisModel(models.Model):
    """
    Common parts of IAE and GEIQ eligibility diagnosis model
    """

    EXPIRATION_DELAY_MONTHS = 6

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="auteur",
        on_delete=models.CASCADE,
        # removed clashing on former unused related_name `eligibility_diagnoses_made`
    )
    author_kind = models.CharField(
        verbose_name="type de l'auteur",
        max_length=10,
        choices=AuthorKind.choices,
        default=AuthorKind.PRESCRIBER,
    )
    # When the author is a prescriber, keep a track of his current organization.
    author_prescriber_organization = models.ForeignKey(
        "prescribers.PrescriberOrganization",
        verbose_name="organisation du prescripteur de l'auteur",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(verbose_name="date de modification", auto_now=True, db_index=True)
    expires_at = models.DateTimeField(verbose_name="date d'expiration", db_index=True)

    class Meta:
        abstract = True

    def __str__(self):
        return str(self.pk)

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = self.created_at + relativedelta(months=self.EXPIRATION_DELAY_MONTHS)
        return super().save(*args, **kwargs)

    @property
    def is_valid(self):
        return bool(self.expires_at and self.expires_at > timezone.now())


class AdministrativeCriteriaQuerySet(models.QuerySet):
    def level1(self):
        return self.filter(level=AdministrativeCriteriaLevel.LEVEL_1)

    def level2(self):
        return self.filter(level=AdministrativeCriteriaLevel.LEVEL_2)

    def for_job_application(self, job_application):
        return self.filter(eligibilitydiagnosis__jobapplication=job_application)


class AbstractAdministrativeCriteria(models.Model):
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

    class Meta:
        abstract = True

    objects = AdministrativeCriteriaQuerySet.as_manager()

    def __str__(self):
        name = f"{self.name}"
        if level_display := self.get_level_display():
            name += f" - {level_display}"
        return name
