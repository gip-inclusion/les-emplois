import secrets

from django.db import models
from django.utils import timezone

from itou.common_apps.address.departments import DEPARTMENTS
from itou.companies.models import Company


def _generate_key():
    return secrets.token_urlsafe()


class CompanyToken(models.Model):
    key = models.CharField(default=_generate_key, unique=True, editable=False)
    label = models.CharField(verbose_name="mémo permettant d'identifier l'usage du jeton", max_length=60, unique=True)
    created_at = models.DateTimeField(default=timezone.now)
    companies = models.ManyToManyField(Company, related_name="api_tokens")

    class Meta:
        verbose_name = "jeton d'API entreprise"
        verbose_name_plural = "jetons d'API entreprise"

    def datadog_info(self):
        """Method returning the token representation in our Datadog logs (no secret here!)"""
        return f"CompanyToken-{self.pk}"


class DepartmentToken(models.Model):
    key = models.CharField(default=_generate_key, unique=True)
    department = models.CharField(
        verbose_name="département",
        choices=DEPARTMENTS.items(),
        max_length=3,
    )
    label = models.CharField(verbose_name="mémo permettant d'identifier l'usage du jeton", max_length=60, unique=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "jeton d'API département"
        verbose_name_plural = "jetons d'API département"

    def __str__(self):
        return self.label

    def datadog_info(self):
        """Method returning the token representation in our Datadog logs (no secret here!)"""
        return f"DepartmentToken-{self.pk}-for-{self.department}"
