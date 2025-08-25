from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models

from itou.cities.models import City
from itou.common_apps.address.departments import DEPARTMENTS
from itou.companies.enums import CompanyKind, ContractType
from itou.jobs.models import ROME_DOMAINS


class SavedSearch(models.Model):
    SEARCH_KINDS = [("COMPANIES", "companies"), ("JOB_APPLICATIONS", "job_applications")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="utilisateur", on_delete=models.CASCADE)
    name = models.CharField(max_length=50, verbose_name="nom de la recherche")
    city = models.ForeignKey(City, verbose_name="ville", on_delete=models.SET_NULL, null=True)
    distance = models.IntegerField(verbose_name="distance", null=True)
    company_kinds = ArrayField(
        base_field=models.CharField(choices=CompanyKind.choices), verbose_name="types de structure", null=True
    )
    departments = ArrayField(
        base_field=models.CharField(choices=DEPARTMENTS.items()), verbose_name="départements", null=True
    )
    # TODO: arrondissement
    contract_types = ArrayField(
        base_field=models.CharField(choices=ContractType.choices), verbose_name="types de contrat", null=True
    )
    domains = ArrayField(
        base_field=models.CharField(choices=ROME_DOMAINS.items()), verbose_name="domaines métier", null=True
    )
    created_at = models.DateTimeField(verbose_name="date de création", auto_now=True)

    class Meta:
        verbose_name = "Recherche sauvegardée"
        verbose_name_plural = "Recherches sauvegardées"
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["user", "name"], name="search_name_unique")]
