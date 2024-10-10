import datetime

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.db import models
from django.utils import timezone

from itou.eligibility.enums import AdministrativeCriteriaKind, AdministrativeCriteriaLevel, AuthorKind
from itou.job_applications.enums import SenderKind
from itou.utils.apis.api_particulier import APIParticulierClient
from itou.utils.models import InclusiveDateRangeField
from itou.utils.types import InclusiveDateRange


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

    @property
    def is_from_employer(self):
        return self.author_kind in (AuthorKind.GEIQ, AuthorKind.EMPLOYER)

    def criteria_can_be_certified(self):
        return self.is_from_employer and self.administrative_criteria.certifiable().exists()

    def get_author_kind_display(self):
        if self.sender_kind == SenderKind.PRESCRIBER and (
            not self.sender_prescriber_organization or not self.sender_prescriber_organization.is_authorized
        ):
            return "Orienteur"
        else:
            return SenderKind(self.sender_kind).label

    def certify_criteria(self):
        SelectedAdministrativeCriteria = self.administrative_criteria.through
        criteria = list(
            SelectedAdministrativeCriteria.objects.filter(
                administrative_criteria__kind__in=AbstractAdministrativeCriteria.CAN_BE_CERTIFIED_KINDS,
                eligibility_diagnosis=self,
            )
        )
        for criterion in criteria:
            criterion.certify()
        SelectedAdministrativeCriteria.objects.bulk_update(
            criteria,
            fields=[
                "data_returned_by_api",
                "certified",
                "certification_period",
                "certified_at",
            ],
        )

    def get_criteria_display_qs(self, hiring_start_at=None):
        return self.selected_administrative_criteria.with_is_considered_certified(hiring_start_at=hiring_start_at)


class AdministrativeCriteriaQuerySet(models.QuerySet):
    def level1(self):
        return self.filter(level=AdministrativeCriteriaLevel.LEVEL_1)

    def level2(self):
        return self.filter(level=AdministrativeCriteriaLevel.LEVEL_2)

    def for_job_application(self, job_application):
        return self.filter(eligibilitydiagnosis__jobapplication=job_application)

    @property
    def certifiable_lookup(self):
        return models.Q(kind__in=AbstractAdministrativeCriteria.CAN_BE_CERTIFIED_KINDS)

    def certifiable(self):
        return self.filter(self.certifiable_lookup)

    def not_certifiable(self):
        return self.exclude(self.certifiable_lookup)


class AbstractAdministrativeCriteria(models.Model):
    MAX_UI_RANK = 32767
    # RSA only for the moment. AAH and PI to come.
    CAN_BE_CERTIFIED_KINDS = [
        AdministrativeCriteriaKind.RSA,
    ]

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
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="créé par",
        null=True,
        blank=True,
        on_delete=models.RESTRICT,  # For traceability and accountability
    )

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
        return self.kind in self.CAN_BE_CERTIFIED_KINDS


class SelectedAdministrativeCriteriaQuerySet(models.QuerySet):
    def with_is_considered_certified(self, hiring_start_at=None):
        if not hiring_start_at:
            # could be:
            # is_certified = models.Q(certification_period__contains=timezone.now())
            # but not validated by UX for the moment.
            is_certified = models.Value(False)
        else:
            validity_period = InclusiveDateRange(
                hiring_start_at - datetime.timedelta(days=self.model.CERTIFICATION_GRACE_PERIOD_DAYS),
                hiring_start_at,
            )
            is_certified = models.Q(certification_period__overlap=validity_period, certified=True)
        return self.annotate(is_considered_certified=is_certified)


class AbstractSelectedAdministrativeCriteria(models.Model):
    CERTIFICATION_GRACE_PERIOD_DAYS = 90

    certified = models.BooleanField(blank=True, null=True, verbose_name="certifié par l'API Particulier")
    certified_at = models.DateTimeField(blank=True, null=True, verbose_name="certifié le")
    certification_period = InclusiveDateRangeField(blank=True, null=True, verbose_name="période de certification")
    data_returned_by_api = models.JSONField(
        blank=True, null=True, verbose_name="résultat renvoyé par l'API Particulier"
    )

    class Meta:
        abstract = True

    objects = SelectedAdministrativeCriteriaQuerySet.as_manager()

    def certify(self, save=False):
        client = APIParticulierClient(job_seeker=self.eligibility_diagnosis.job_seeker)

        # Call only if self.certified is None?
        if self.administrative_criteria.is_certifiable:
            # Only the RSA criterion is certifiable at the moment,
            # but this may change soon with the addition of `parent isolé` and `allocation adulte handicapé`.
            if self.administrative_criteria.kind == AdministrativeCriteriaKind.RSA:
                data = client.revenu_solidarite_active()

            self.certified_at = timezone.now()
            self.data_returned_by_api = data["raw_response"]
            self.certified = data["is_certified"]
            self.certification_period = None
            start_at, end_at = data["start_at"], data["end_at"]
            if start_at and end_at:
                self.certification_period = InclusiveDateRange(start_at, end_at)

        if save:
            self.save()
