import datetime
import logging

from django.conf import settings
from django.db import models
from django.utils import timezone

from itou.eligibility.enums import (
    CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS,
    AdministrativeCriteriaKind,
    AdministrativeCriteriaLevel,
    AuthorKind,
)
from itou.eligibility.tasks import async_certify_criteria, certify_criteria
from itou.job_applications.enums import SenderKind
from itou.utils.models import InclusiveDateRangeField


logger = logging.getLogger(__name__)


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
        on_delete=models.RESTRICT,  # For traceability and accountability
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
        on_delete=models.RESTRICT,  # For traceability and accountability
    )
    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(verbose_name="date de modification", auto_now=True, db_index=True)
    expires_at = models.DateField(
        verbose_name="date d'expiration",
        db_index=True,
        help_text="Diagnosic expiré à compter de ce jour",
    )

    class Meta:
        abstract = True

    def __str__(self):
        return str(self.pk)

    @property
    def is_valid(self):
        return self.expires_at > timezone.localdate()

    @property
    def is_from_employer(self):
        return self.author_kind in (AuthorKind.GEIQ, AuthorKind.EMPLOYER)

    def criteria_can_be_certified(self):
        return self.administrative_criteria.certifiable().exists()

    def get_author_kind_display(self):
        if self.sender_kind == SenderKind.PRESCRIBER and (
            not self.sender_prescriber_organization or not self.sender_prescriber_organization.is_authorized
        ):
            return "Orienteur"
        else:
            return SenderKind(self.sender_kind).label

    def certify_criteria(self):
        try:
            # Optimistic call to show certified badge in response immediately.
            certify_criteria(self)
        except Exception:  # Do not fail the web request if the criteria could not be certified.
            logger.info("Could not certify criteria synchronously.", exc_info=True)
            async_certify_criteria(self._meta.model_name, self.pk)


class AdministrativeCriteriaQuerySet(models.QuerySet):
    def level1(self):
        return self.filter(level=AdministrativeCriteriaLevel.LEVEL_1)

    def level2(self):
        return self.filter(level=AdministrativeCriteriaLevel.LEVEL_2)

    @property
    def certifiable_lookup(self):
        return models.Q(kind__in=CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS)

    def certifiable(self):
        return self.filter(self.certifiable_lookup)

    def not_certifiable(self):
        return self.exclude(self.certifiable_lookup)


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
    kind = models.CharField(
        verbose_name="type",
        choices=AdministrativeCriteriaKind.choices,
        default="",
    )
    # Used to rank criteria in UI. Should be set by level (LEVEL_1: 1, 2, 3… LEVEL_2: 1, 2, 3…).
    # Default value is MAX_UI_RANK so that it's pushed at the end if `ui_rank` is forgotten.
    ui_rank = models.PositiveSmallIntegerField(default=MAX_UI_RANK)
    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now)

    class Meta:
        abstract = True

    objects = AdministrativeCriteriaQuerySet.as_manager()

    def __str__(self):
        name = f"{self.name}"
        if level_display := self.get_level_display():
            name += f" - {level_display}"
        return name

    @property
    def is_certifiable(self):
        return self.kind in CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS


class AbstractSelectedAdministrativeCriteria(models.Model):
    CERTIFICATION_GRACE_PERIOD_DAYS = 92

    certified = models.BooleanField(blank=True, null=True, verbose_name="certifié par l'API Particulier")
    certified_at = models.DateTimeField(blank=True, null=True, verbose_name="certifié le")
    certification_period = InclusiveDateRangeField(blank=True, null=True, verbose_name="période de certification")
    data_returned_by_api = models.JSONField(
        blank=True, null=True, verbose_name="résultat renvoyé par l'API Particulier"
    )
    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now)

    class Meta:
        abstract = True
