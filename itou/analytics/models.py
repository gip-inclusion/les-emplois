import uuid

from django.db import models
from django.utils import timezone


class DatumCode(models.TextChoices):
    # Employee record - Base
    EMPLOYEE_RECORD_COUNT = "ER-001", "FS totales"
    EMPLOYEE_RECORD_DELETED = "ER-002", "FS (probablement) supprimées"
    # Employee record - Lifecycle
    EMPLOYEE_RECORD_PROCESSED_AT_FIRST_EXCHANGE = "ER-101", "FS intégrées (0000) au premier retour"
    EMPLOYEE_RECORD_WITH_ERROR_AT_FIRST_EXCHANGE = "ER-102", "FS avec une erreur au premier retour"
    EMPLOYEE_RECORD_WITH_ERROR_3436_AT_FIRST_EXCHANGE = "ER-102-3436", "FS avec une erreur 3436 au premier retour"
    EMPLOYEE_RECORD_WITH_AT_LEAST_ONE_ERROR = "ER-103", "FS ayant eu au moins un retour en erreur"


class Datum(models.Model):
    """Store an aggregated `value` of the `code` data point for the specified `bucket`."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4)

    code = models.TextField(choices=DatumCode.choices)
    bucket = models.TextField()
    value = models.IntegerField()  # Integer offers the best balance between range, storage size, and performance

    measured_at = models.DateTimeField(default=timezone.now)  # Not using auto_now_add=True to allow overrides

    class Meta:
        verbose_name_plural = "Data"
        unique_together = ["code", "bucket"]
        indexes = [models.Index(fields=["measured_at", "code"])]
