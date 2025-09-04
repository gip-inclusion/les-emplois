from django.conf import settings
from django.db import models
from django.http import QueryDict
from django.urls import reverse

from itou.cities.models import City
from itou.common_apps.address.departments import format_district
from itou.jobs.models import ROME_DOMAINS
from itou.utils.templatetags.str_filters import pluralizefr


class SavedSearch(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="utilisateur", on_delete=models.CASCADE)
    name = models.CharField(max_length=50, verbose_name="nom de la recherche")
    query_params = models.CharField(verbose_name="paramètres de la recherche")
    created_at = models.DateTimeField(verbose_name="date de création", auto_now=True)

    class Meta:
        verbose_name = "recherche sauvegardée"
        verbose_name_plural = "recherches sauvegardées"
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["user", "name"], name="search_name_unique")]

    def __str__(self):
        return self.name

    @property
    def url(self):
        return f"{reverse('search:employers_results')}?{self.query_params}"

    @property
    def display_details(self):
        def filter_ellipsis(elements, max_nb):
            if len(elements) <= max_nb:
                return ", ".join(elements)
            return ", ".join(elements[:max_nb]) + ", +" + str(len(elements) - max_nb)

        query_dict = QueryDict(self.query_params)

        details = []

        city = City.objects.filter(slug=query_dict.get("city")).first()
        if city:
            details = [city.name]

        distance = f"Distance : {query_dict.get('distance', '25')} km"
        details.append(distance)

        if city and (districts := query_dict.getlist(f"districts_{city.department}")):
            districts = [format_district(post_code=d, department=city.department) for d in districts]
            districts_str = f"{', '.join(districts)} arrondissement{pluralizefr(districts)}"
            details.append(districts_str)

        if kinds := query_dict.getlist("kinds"):
            kinds_str = (f"Type{pluralizefr(kinds)} de structure : " + filter_ellipsis(kinds, 5)) if kinds else None
            details.append(kinds_str)

        if city and (departments := query_dict.getlist("departments")):
            details.append(f"Département{pluralizefr(departments)} : {', '.join(departments)}")

        if contract_types := query_dict.getlist("contract_types"):
            from itou.www.search_views.forms import JobDescriptionSearchForm

            CONTRACT_TYPE_DICT = dict(JobDescriptionSearchForm.CONTRACT_TYPE_CHOICES)
            contract_types_str = f"Type{pluralizefr(contract_types)} de contrats : " + filter_ellipsis(
                [CONTRACT_TYPE_DICT.get(contract) for contract in contract_types], 3
            )
            details.append(contract_types_str)

        if domains := query_dict.getlist("domains"):
            domains_str = f"Domaine{pluralizefr(domains)} : " + filter_ellipsis(
                [ROME_DOMAINS.get(domain) for domain in domains], 2
            )
            details.append(domains_str)

        return " – ".join(details)
