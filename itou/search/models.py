from django.conf import settings
from django.db import models
from django.http import QueryDict
from django.urls import reverse

from itou.cities.models import City
from itou.utils.templatetags.str_filters import pluralizefr


MAX_SAVED_SEARCHES_COUNT = 20


class SavedSearch(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="utilisateur", related_name="saved_searches", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=50, verbose_name="nom de la recherche")
    query_params = models.CharField(verbose_name="paramètres de la recherche")
    created_at = models.DateTimeField(verbose_name="date de création", auto_now=True)

    class Meta:
        verbose_name = "recherche enregistrée"
        verbose_name_plural = "recherches enregistrées"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "name"],
                name="unique_%(class)s_name_per_user",
                violation_error_message="Une recherche existe déjà avec ce nom.",
            )
        ]

    def __str__(self):
        return self.name

    def get_city_slug(self):
        return QueryDict(self.query_params).get("city")

    @staticmethod
    def add_city_name_attr(saved_searches):
        saved_searches = list(saved_searches)
        slugs = [saved_search.get_city_slug() for saved_search in saved_searches]
        cities = {city.slug: city.name for city in City.objects.filter(slug__in=slugs)}

        for saved_search in saved_searches:
            slug = saved_search.get_city_slug()
            setattr(saved_search, "city_name", cities.get(slug))

        return saved_searches

    @property
    def url(self):
        return f"{reverse('search:employers_results')}?{self.query_params}"

    @property
    def display_details(self):
        query_dict = QueryDict(self.query_params, mutable=True)

        details = []

        # city_name is added in views with SavedSearch.add_city_name_attr()
        if city_name := getattr(self, "city_name"):
            details.append(city_name)
        query_dict.pop("city", None)

        distance = f"Distance : {query_dict.pop('distance', ['25'])[0]} km"
        details.append(distance)

        if kinds := query_dict.pop("kinds", None):
            kinds_str = f"Type{pluralizefr(kinds)} de structure : {', '.join(kinds)}"
            details.append(kinds_str)

        if departments := query_dict.pop("departments", None):
            details.append(f"Département{pluralizefr(departments)} : {', '.join(departments)}")

        other_filters_str = f" + {len(query_dict)} filtre{pluralizefr(query_dict)}" if query_dict else ""

        return " – ".join(details) + other_filters_str
