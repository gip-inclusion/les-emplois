from django.conf import settings
from django.db import models

from itou.job_applications.models import JobApplication


class Note(models.Model):
    job_application = models.OneToOneField(
        JobApplication,
        on_delete=models.CASCADE,
        related_name="premium_note",
        verbose_name="candidature",
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
