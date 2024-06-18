import uuid

from django.db import models
from django.utils import timezone

from itou.common_apps.address.departments import DEPARTMENTS
from itou.users.enums import UserKind


class DatumCode(models.TextChoices):
    # Employee record - Base
    EMPLOYEE_RECORD_COUNT = "ER-001", "FS totales"
    EMPLOYEE_RECORD_DELETED = "ER-002", "FS (probablement) supprimées"
    # Employee record - Lifecycle
    EMPLOYEE_RECORD_PROCESSED_AT_FIRST_EXCHANGE = "ER-101", "FS intégrées (0000) au premier retour"
    EMPLOYEE_RECORD_WITH_ERROR_AT_FIRST_EXCHANGE = "ER-102", "FS avec une erreur au premier retour"
    EMPLOYEE_RECORD_WITH_ERROR_3436_AT_FIRST_EXCHANGE = "ER-102-3436", "FS avec une erreur 3436 au premier retour"
    EMPLOYEE_RECORD_WITH_AT_LEAST_ONE_ERROR = "ER-103", "FS ayant eu au moins un retour en erreur"
    # Approval - Base
    APPROVAL_COUNT = "AP-001", "PASS IAE total"
    APPROVAL_CANCELLED = "AP-002", "PASS IAE annulés"
    # Approval - PE notification cycle
    APPROVAL_PE_NOTIFY_SUCCESS = "AP-101", "PASS IAE synchronisés avec succès avec pole emploi"
    APPROVAL_PE_NOTIFY_PENDING = "AP-102", "PASS IAE en attente de synchronisation avec pole emploi"
    APPROVAL_PE_NOTIFY_ERROR = "AP-103", "PASS IAE en erreur de synchronisation avec pole emploi"
    APPROVAL_PE_NOTIFY_READY = "AP-104", "PASS IAE prêts à être synchronisés avec pole emploi"
    # Users
    USER_COUNT = "US-001", "Nombre d'utilisateurs"
    USER_JOB_SEEKER_COUNT = "US-011", "Nombre de demandeurs d'emploi"
    USER_PRESCRIBER_COUNT = "US-012", "Nombre de prescripteurs"
    USER_EMPLOYER_COUNT = "US-013", "Nombre d'employeurs"
    USER_LABOR_INSPECTOR_COUNT = "US-014", "Nombre d'inspecteurs du travail"
    USER_ITOU_STAFF_COUNT = "US-015", "Nombre d'administrateurs"
    # API usage
    API_TOTAL_CALLS = "API-001", "API : total d'appels reçus"
    API_TOTAL_UV = "API-002", "API : total de visiteurs uniques"
    API_TOTAL_CALLS_CANDIDATS = "API-003", "API candidats : total d'appels reçus"
    API_TOTAL_UV_CANDIDATS = "API-004", "API candidats : total de visiteurs uniques"
    API_TOTAL_CALLS_GEIQ = "API-005", "API GEIQ : total d'appels reçus"
    API_TOTAL_UV_GEIQ = "API-006", "API GEIQ : total de visiteurs uniques"
    API_TOTAL_CALLS_ER = "API-007", "API FS : total d'appels reçus"
    API_TOTAL_UV_ER = "API-008", "API FS : total de visiteurs uniques"
    API_TOTAL_CALLS_MARCHE = "API-009", "API Le marché : total d'appels reçus"
    API_TOTAL_CALLS_SIAES = "API-010", "API siaes : total d'appels reçus"
    API_TOTAL_UV_SIAES = "API-011", "API siaes : total de visiteurs uniques (par adresse IP)"
    API_TOTAL_CALLS_STRUCTURES = "API-012", "API structures : total d'appels reçus"


class Datum(models.Model):
    """Store an aggregated `value` of the `code` data point for the specified `bucket`."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4)

    code = models.TextField(choices=DatumCode.choices)
    bucket = models.TextField()
    value = models.IntegerField()  # Integer offers the best balance between range, storage size, and performance

    measured_at = models.DateTimeField(default=timezone.now)  # Not using auto_now_add=True to allow overrides

    class Meta:
        verbose_name_plural = "data"
        unique_together = ["code", "bucket"]
        indexes = [models.Index(fields=["measured_at", "code"])]


class StatsDashboardVisit(models.Model):
    dashboard_id = models.IntegerField(verbose_name="ID tableau de bord Metabase")
    dashboard_name = models.TextField(verbose_name="nom de la vue du tableau de bord")
    department = models.CharField(verbose_name="département", choices=DEPARTMENTS.items(), max_length=3, null=True)
    region = models.TextField(verbose_name="région", null=True)
    current_company_id = models.IntegerField(verbose_name="ID entreprise courante", null=True)
    current_prescriber_organization_id = models.IntegerField(
        verbose_name="ID organisation prescriptrice courante", null=True
    )
    current_institution_id = models.IntegerField(verbose_name="ID institution courante", null=True)
    user_kind = models.TextField(verbose_name="type d'utilisateur", choices=UserKind.choices)
    user_id = models.IntegerField(verbose_name="ID utilisateur")

    measured_at = models.DateTimeField(default=timezone.now)  # Not using auto_now_add=True to allow overrides

    class Meta:
        verbose_name_plural = "visite de tableau de bord"
