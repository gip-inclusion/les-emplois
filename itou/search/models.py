from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models

from itou.cities.models import City
from itou.common_apps.address.departments import DEPARTMENTS
from itou.companies.enums import CompanyKind
from itou.jobs.models import ROME_DOMAINS


class SavedSearch(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="utilisateur", on_delete=models.CASCADE)
    name = models.CharField(max_length=50, verbose_name="nom de la recherche")
    city = models.ForeignKey(City, verbose_name="ville", on_delete=models.CASCADE)
    distance = models.IntegerField(verbose_name="distance")
    kinds = ArrayField(
        base_field=models.CharField(choices=CompanyKind.choices),
        verbose_name="types de structure",
        null=True,
        blank=True,
    )
    departments = ArrayField(
        base_field=models.CharField(choices=DEPARTMENTS.items()), verbose_name="départements", null=True, blank=True
    )
    districts = models.JSONField(verbose_name="arrondissements", null=True, blank=True)
    contract_types = ArrayField(
        base_field=models.CharField(
            blank=True
        ),  # No choices here as the search form contains more than companies.enums.ContractType
        verbose_name="types de contrat",
        null=True,
        blank=True,
    )
    domains = ArrayField(
        base_field=models.CharField(choices=ROME_DOMAINS.items()),
        verbose_name="domaines métier",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(verbose_name="date de création", auto_now=True)

    class Meta:
        verbose_name = "Recherche sauvegardée"
        verbose_name_plural = "Recherches sauvegardées"
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["user", "name"], name="search_name_unique")]

    def __str__(self):
        return self.name
