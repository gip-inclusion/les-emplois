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
    {"code": "97108", "name": "CAPESTERRE-BELLE-EAU"},
    {"code": "37273", "name": "VILLE-AUX-DAMES"},
    {"code": "13200", "name": "MARSEILLE"},
    {"code": "67152", "name": "GEISPOLSHEIM"},
]


class CountryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.Country


class CountryFranceFactory(CountryFactory):
    code, name, group = "100", "FRANCE", "1"


class CountryFranceOtherFactory(CountryFactory):
    """
    Parts of France but having their own INSEE country code

    Most of them are "Collectivités d'Outre-Mer"
    """

    code, name, group = random.choice(_sample_france).values()


class CountryEuropeFactory(CountryFactory):
    code, name, group = random.choice(_sample_europe_countries).values()


class CountryOutsideEuropeFactory(CountryFactory):
    code, name, group = random.choice(_sample_outside_europe_countries).values()


class CommuneFactory(factory.django.DjangoModelFactory):
    """
    Factory for ASP INSEE commune
    """

    class Meta:
        model = models.Commune

    start_date = datetime.date(2000, 1, 1)
    end_date = None

    code, name = random.choice(_sample_communes).values()


class MockedCommuneFactory(CommuneFactory):
    """
    A factory with a specific code for mock testing
    """

    code, name = _sample_communes[-1].values()
