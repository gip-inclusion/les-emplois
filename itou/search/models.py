from django.conf import settings
from django.db import models
from django.http import QueryDict
from django.urls import reverse

from itou.cities.models import City
from itou.utils.templatetags.str_filters import pluralizefr


MAX_SAVED_SEARCHES_COUNT = 20


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
        query_dict = QueryDict(self.query_params, mutable=True)

        details = []

        city = City.objects.filter(slug=query_dict.pop("city", [None])[0]).first()
        if city:
            details = [city.name]

        distance = f"Distance : {query_dict.pop('distance', ['25'])[0]} km"
        details.append(distance)

        if kinds := query_dict.pop("kinds", None):
            kinds_str = f"Type{pluralizefr(kinds)} de structure : " + ", ".join(kinds)
            details.append(kinds_str)

        if city and (departments := query_dict.pop("departments", None)):
            details.append(f"Département{pluralizefr(departments)} : {', '.join(departments)}")

        other_filters_str = f" + {len(query_dict)} filtre{pluralizefr(query_dict)}" if query_dict else ""

        return " – ".join(details) + other_filters_str
