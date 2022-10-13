import datetime
import random

import factory

from itou.asp import models


_sample_europe_countries = [
    {"code": "101", "name": "DANEMARK", "group": "2"},
    {"code": "111", "name": "BULGARIE", "group": "2"},
    {"code": "135", "name": "PAYS-BAS", "group": "2"},
]

_sample_outside_europe_countries = [
    {"code": "212", "name": "AFGHANISTAN", "group": "3"},
    {"code": "436", "name": "BAHAMAS", "group": "3"},
    {"code": "324", "name": "CONGO", "group": "3"},
]

_sample_france = [
    {"code": "714", "name": "BORA-BORA", "group": "1"},
    {"code": "812", "name": "KOUMAC", "group": "1"},
    {"code": "737", "name": "PUKAPUKA", "group": "1"},
]

_sample_communes = [
    {"code": "64483", "name": "SAINT-JEAN-DE-LUZ"},
    {"code": "97108", "name": "CAPESTERRE-DE-MARIE-GALANT"},
    {"code": "97107", "name": "CAPESTERRE-BELLE-EAU"},
    {"code": "37273", "name": "VILLE-AUX-DAMES"},
    {"code": "13200", "name": "MARSEILLE"},
    {"code": "67152", "name": "GEISPOLSHEIM"},
    {"code": "85146", "name": "MONTAIGU"},
]


class CountryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.Country
        django_get_or_create = ("code",)

    code, name, group = random.choice(_sample_europe_countries).values()


class CountryFranceFactory(CountryFactory):
    code, name, group = "100", "FRANCE", "1"


class CountryCollectiviteOutremerFactory(CountryFactory):
    """
    Parts or regions of France having their own INSEE country code

    Most of them are "Collectivités d'Outre-Mer"
    """

    code, name, group = random.choice(_sample_france).values()


class CountryEuropeFactory(CountryFactory):
    code, name, group = random.choice(_sample_europe_countries).values()


class CountryOutsideEuropeFactory(CountryFactory):
    code, name, group = random.choice(_sample_outside_europe_countries).values()


class CommuneFactory(factory.django.DjangoModelFactory):
    """Factory for ASP INSEE commune:
    - if `code` or `name` are build parameters, object values will result of a lookup in `_sample_communes`
    - otherwise, fields `code` and `name` will be set from a randomly picked sample commune
    """

    class Meta:
        model = models.Commune
        django_get_or_create = (
            "code",
            "start_date",
            "end_date",
        )

    # FIXME: may cause issues in testing validity periods
    start_date = datetime.date(2000, 1, 1)
    end_date = None

    # Skipping definition of `code` and `name` fields
    # will be set in `_adjust_kwargs`

    @classmethod
    def _adjust_kwargs(cls, **kwargs):
        # Allow creation with parameters `code` or `name` (first matched)
        # either field must be a match in `_sample_communes`
        match kwargs:
            case {"code": code}:
                for item in _sample_communes:
                    if item["code"] == code:
                        kwargs["name"] = item["name"]
            case {"name": name}:
                for item in _sample_communes:
                    if item["name"] == name:
                        kwargs["code"] = item["code"]
            case _:
                code, name = random.choice(_sample_communes).values()
                kwargs["code"] = code
                kwargs["name"] = name

        return kwargs

    @classmethod
    def _adjust_kwargs(cls, **kwargs):
        # Allow creation with parameters `code` or `name` (first matched)
        # either field must be a match in `_sample_communes`
        match kwargs:
            case {"code": code}:
                for item in _sample_communes:
                    if item["code"] == code:
                        kwargs["name"] = item["name"]
            case {"name": name}:
                for item in _sample_communes:
                    if item["name"] == name:
                        kwargs["code"] = item["code"]
            case _:
                code, name = random.choice(_sample_communes).values()
                kwargs["code"] = code
                kwargs["name"] = name

        return kwargs


# FIXME: unreliable and confusing
class MockedCommuneFactory(CommuneFactory):
    """
    A factory with a specific code for mock testing
    """

    code, name = _sample_communes[-1].values()
