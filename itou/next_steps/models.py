from django.conf import settings
from django.db import models
from django.utils import timezone

from itou.companies.enums import ProSupportReportBarrier


class BarrierStatus(models.TextChoices):
    CONFIRMED = "CONFIRMED", "confirmé"
    DISMISSED = "DISMISSED", "écarté"


class JobSeekerBarrierQuerySet(models.QuerySet):
    def latest_by_barrier(self):
        """The latest statement on each barrier, by barrier."""
        latest = {}
        for statement in self.order_by("-created_at", "-pk"):
            latest.setdefault(statement.barrier, statement)
        return latest


class JobSeekerBarrier(models.Model):
    """A barrier a professional confirmed or dismissed for a job seeker, when validating their eligibility.

    A history: each validation adds statements, and the latest on a barrier prevails over the eligibility criteria
    that hint at it, until a later report says otherwise. RGPD: to be validated by the team before production.
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
    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now, db_index=True)

    objects = JobSeekerBarrierQuerySet.as_manager()

    class Meta:
        verbose_name = "frein à lever"
        verbose_name_plural = "freins à lever"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_barrier_display()} · {self.get_status_display()}"
