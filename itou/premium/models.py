from django.conf import settings
from django.db import models

from itou.approvals.models import Suspension
from itou.companies.models import Company
from itou.job_applications.models import JobApplication


class Customer(models.Model):
    company = models.OneToOneField(
        Company,
        on_delete=models.CASCADE,
        related_name="premium_customer",
        verbose_name="entreprise",
    )
    end_subscription_date = models.DateField(verbose_name="date de fin d'abonnement")
    last_synced_at = models.DateTimeField(verbose_name="dernière synchronisation")

    class Meta:
        verbose_name = "client"
        verbose_name_plural = "clients"

    def __str__(self):
        return self.company.name


class SyncedJobApplication(models.Model):
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name="synced_job_applications",
        verbose_name="client",
    )
    job_application = models.OneToOneField(
        JobApplication,
        on_delete=models.CASCADE,
        related_name="synced_job_application",
        verbose_name="candidature",
    )
    last_in_progress_suspension = models.ForeignKey(
        Suspension,
        on_delete=models.SET_NULL,
        related_name="synced_job_applications",
        verbose_name="dernière suspension en cours",
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "candidature synchronisée"
        verbose_name_plural = "candidatures synchronisées"

    def __str__(self):
        return str(self.job_application.pk)


class Note(models.Model):
    synced_job_application = models.OneToOneField(
        SyncedJobApplication,
        on_delete=models.CASCADE,
        related_name="notes",
        verbose_name="synced_job_application",
    )
    content = models.TextField(default=None, blank=True, null=True, verbose_name="content")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="date de création")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="date de modification")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="créé par",
        on_delete=models.SET_NULL,
        related_name="job_seeker_informations_created_by",
        null=True,
        blank=True,
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="modifié par",
        on_delete=models.SET_NULL,
        related_name="job_seeker_informations_updated_by",
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "note sur la candidature"
        verbose_name_plural = "notes sur les candidatures"
