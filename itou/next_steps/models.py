from django.conf import settings
from django.db import models
from django.utils import timezone

from itou.companies.enums import ProSupportReportBarrier


class BarrierStatus(models.TextChoices):
    CONFIRMED = "CONFIRMED", "confirmé"
    DISMISSED = "DISMISSED", "écarté"
    LIFTED = "LIFTED", "levé"


class LiftCause(models.TextChoices):
    """What lifted a barrier, as its author says: a choice, never free text."""

    ORIENTATION = "ORIENTATION", "l’orientation vers un service"
    SELF = "SELF", "la personne a trouvé une solution elle-même"
    OTHER = "OTHER", "autre"


class JobSeekerBarrierQuerySet(models.QuerySet):
    def latest_by_barrier(self):
        """The latest statement on each barrier, by barrier."""
        latest = {}
        for statement in self.order_by("-created_at", "-pk"):
            latest.setdefault(statement.barrier, statement)
        return latest


class JobSeekerBarrier(models.Model):
    """A barrier a professional stated for a job seeker: confirmed or dismissed when validating their eligibility,
    lifted or back from the barriers' cards.

    A history: each statement adds a row, and the latest on a barrier prevails over the eligibility criteria that
    hint at it, until a later report says otherwise. RGPD: to be validated by the team before production.
    """

    job_seeker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="usager",
        on_delete=models.CASCADE,
        related_name="next_steps_barriers",
    )
    barrier = models.CharField(verbose_name="frein", max_length=20, choices=ProSupportReportBarrier.choices)
    status = models.CharField(verbose_name="statut", max_length=20, choices=BarrierStatus.choices)
    # The diagnosis the statement was made with.
    eligibility_diagnosis = models.ForeignKey(
        "eligibility.EligibilityDiagnosis",
        verbose_name="diagnostic d’éligibilité",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="auteur",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    author_prescriber_organization = models.ForeignKey(
        "prescribers.PrescriberOrganization",
        verbose_name="organisation de l’auteur",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    author_company = models.ForeignKey(
        "companies.Company",
        verbose_name="structure de l’auteur",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    # For a lifted barrier: what lifted it, if its author said, and the orientation when it is one.
    lift_cause = models.CharField(verbose_name="levé grâce à", max_length=20, choices=LiftCause.choices, blank=True)
    orientation = models.ForeignKey(
        "insertion.Orientation",
        verbose_name="orientation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now, db_index=True)

    objects = JobSeekerBarrierQuerySet.as_manager()

    class Meta:
        verbose_name = "frein à lever"
        verbose_name_plural = "freins à lever"
        ordering = ["-created_at"]

    @property
    def author_organization(self):
        return self.author_prescriber_organization or self.author_company

    def __str__(self):
        return f"{self.get_barrier_display()} · {self.get_status_display()}"
