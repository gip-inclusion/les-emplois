import json
import os

from django.contrib.gis.geos import GEOSGeometry, Point
from django.template.defaultfilters import slugify

from itou.cities.models import City


CURRENT_DIR = os.path.dirname(os.path.realpath(__file__))

CITIES_JSON_FILE = f"{CURRENT_DIR}/management/commands/data/cities.json"


def create_test_cities(selected_departments, num_per_department=None):
    """
    Not a factory strictly speaking, but it's sitting here for discoverability.

    Pick cities from `cities.json` based on the given department numbers.
        create_test_cities(['01', '02'])

    The number of cities in each department can be limited:
        create_test_cities(['54', '57'], num_per_department=2)
    """
    departments_counter = {department: 0 for department in selected_departments}

    with open(CITIES_JSON_FILE) as raw_json_data:

        json_data = json.load(raw_json_data)

        for item in json_data:

            department = item.get("codeDepartement")
            if (not department) or (department not in selected_departments):
                continue

            coords = item.get("centre")
            if not coords:
                continue

            departments_counter[department] += 1
            if num_per_department and departments_counter[department] > num_per_department:
                if all(value >= num_per_department for value in departments_counter.values()):
                    break
                continue

            City.objects.create(
                slug=slugify(f"{item['nom']}-{department}"),
                department=department,
                name=item["nom"],
                post_codes=item["codesPostaux"],
                code_insee=item["code"],
                coords=GEOSGeometry(f"{coords}"),  # Feed `GEOSGeometry` with GeoJSON.
            )


def create_city_saint_andre():
    return City.objects.create(
        name="Saint-André-des-Eaux",
        slug="saint-andre-des-eaux-44",
        department="44",
        coords=Point(-2.3140436, 47.3618584),
        post_codes=["44117"],
        code_insee="44117",
    )


def create_city_guerande():
    return City.objects.create(
        name="Guérande",
        slug="guerande-44",
        department="44",
        coords=Point(-2.4747713, 47.3358576),
        # Dummy
        post_codes=["44350"],
        code_insee="44350",
    )


def create_city_vannes():
    return City.objects.create(
        name="Vannes",
        slug="vannes-56",
        department="56",
        coords=Point(-2.8186843, 47.657641),
        # Dummy
        post_codes=["56000"],
        code_insee="56260",
    )


def create_city_in_zrr():
    return City.objects.create(
        name="Balaguier d'Olt",
        slug="balaguier-dolt-12",
        department="12",
        post_codes=["12260"],
        code_insee="12018",
        coords=Point(1.9768, 44.5206),
    )


def create_city_partially_in_zrr():
    return City.objects.create(
        name="Petite-Île",
        slug="petite-ile-974",
        department="974",
        post_codes=["97429"],
        code_insee="97405",
        coords=Point(55.5761, -21.3389),
    )
