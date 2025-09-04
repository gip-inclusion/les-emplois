from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.urls import reverse

from itou.cities.models import City
from itou.common_apps.address.departments import DEPARTMENTS, format_district
from itou.companies.enums import CompanyKind
from itou.jobs.models import ROME_DOMAINS
from itou.utils.templatetags.str_filters import pluralizefr


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

    @property
    def url(self):
        return reverse(
            "search:employers_results",
            query={
                "city": self.city.slug,
                "distance": self.distance,
                "kinds": self.kinds,
                "departments": self.departments,
                "contract_types": self.contract_types,
                "domains": self.domains,
            }
            | self.districts,
        )

    @property
    def display_details(self):
        departments_str = (
            f"département{pluralizefr(self.departments)} {', '.join(self.departments)}" if self.departments else None
        )

        districts = [
            format_district(post_code=d, department=self.city.department)
            for d in self.districts.get(f"districts_{self.city.department}", [])
        ]
        districts_str = f"{', '.join(districts)} arrondissement{pluralizefr(districts)}" if districts else None

        kinds_str = ", ".join(self.kinds) if self.kinds else None

        domains_str = (
            ", ".join([ROME_DOMAINS.get(domain) for domain in self.domains])
            if self.domains and len(self.domains) <= 2
            else None
        )

        from itou.www.search_views.forms import JobDescriptionSearchForm

        CONTRACT_TYPE_DICT = dict(JobDescriptionSearchForm.CONTRACT_TYPE_CHOICES)
        contract_types_str = (
            ", ".join([CONTRACT_TYPE_DICT.get(contract) for contract in self.contract_types])
            if self.contract_types
            else None
        )

        return ", ".join(
            filter(
                lambda x: x is not None,
                [
                    self.city.name,
                    f"{self.distance} km",
                    districts_str,
                    kinds_str,
                    departments_str,
                    contract_types_str,
                    domains_str,
                ],
            )
        )
