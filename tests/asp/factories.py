import random

import factory

from itou.asp import models


# These factories are basically wrappers around real model objects inserted via fixtures.
# `Country` and `Commune` objects can be used `as-is` but it is easier to use them with factories
# as other factories are depending on them.

# In order to use these factories, you must load these fixtures:
# - `test_asp_INSEE_communes_factory.json`
# - `test_asp_INSEE_countries_factory.json`
# in your Django unit tests (set `fixtures` field).

_COMMUNES_CODES = ["64483", "97108", "97107", "37273", "13200", "67152", "85146", "58273"]

_FRANCE_CODES = ["100"]
_OTHER_FRANCE_CODES = ["714", "737", "812"]
_EUROPE_COUNTRIES_CODES = ["101", "111", "135"]
_OUTSIDE_EUROPE_COUNTRIES_CODES = ["212", "324", "436"]


class AbstractCountryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.Country
        django_get_or_create = ("code",)
        abstract = True
        strategy = factory.BUILD_STRATEGY

    code = name = pk = None

    @staticmethod
    def _codes_for_zone(zone: str) -> list[dict]:
        match zone:
            case "france":
                codes = _FRANCE_CODES
            case "other_france":
                codes = _OTHER_FRANCE_CODES
            case "europe":
                codes = _EUROPE_COUNTRIES_CODES
            case "outside_europe":
                codes = _OUTSIDE_EUROPE_COUNTRIES_CODES
            case "all":
                codes = _FRANCE_CODES + _OTHER_FRANCE_CODES + _EUROPE_COUNTRIES_CODES + _OUTSIDE_EUROPE_COUNTRIES_CODES
            case _:
                raise Exception(f"Unregistered zone: '{zone}'")
        return models.Country.objects.filter(code__in=codes).values()

    @classmethod
    def _adjust_kwargs(cls, **kwargs):
        if zone := kwargs.get("zone"):
            # If `zone` is given, replace by a random country values from given zone
            kwargs = random.choice(cls._codes_for_zone(zone))
        return kwargs


class CountryFactory(AbstractCountryFactory):
    class Meta:
        model = models.Country

    zone = "all"


class CountryOutsideEuropeFactory(AbstractCountryFactory):
    class Meta:
        model = models.Country

    zone = "outside_europe"


class CountryEuropeFactory(AbstractCountryFactory):
    class Meta:
        model = models.Country

    zone = "europe"


class CountryFranceFactory(AbstractCountryFactory):
    class Meta:
        model = models.Country

    zone = "france"


class CommuneFactory(factory.django.DjangoModelFactory):
    """Factory for ASP INSEE commune:
    - if `code` or `name` are build parameters, object values will taken from the given commune (if available)
    - otherwise, fields `code` and `name` will be set from a randomly picked sample commune
    """

    class Meta:
        model = models.Commune
        django_get_or_create = (
            "code",
            "start_date",
            "end_date",
        )

    @classmethod
    def _adjust_kwargs(cls, **kwargs):
        # Allow creation with parameters `code` or `name` (first matched)
        # either field must be a match in `_sample_communes`
        match kwargs:
            case {"code": code}:
                return models.Commune.objects.filter(code=code).values()[0]
            case {"name": name}:
                return models.Commune.objects.filter(name=name).values()[0]
            case _:
                return random.choice(models.Commune.objects.filter(code__in=_COMMUNES_CODES).values())
