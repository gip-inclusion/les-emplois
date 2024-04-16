import csv
import json
import pathlib

from django.contrib.gis.geos import GEOSGeometry, Point

from itou.cities.models import City


def create_test_cities(selected_departments, num_per_department=None):
    department_map = {dpt: [] for dpt in selected_departments}
    current_dir = pathlib.Path(__file__).parent.resolve()
    with open(current_dir / "sample-cities.csv", encoding="utf-8") as f:
        for line in csv.DictReader(f):
            current_dpt = line["department"]
            if current_dpt not in selected_departments:
                continue
            if len(department_map[current_dpt]) >= num_per_department:
                continue
            line["post_codes"] = json.loads(line["post_codes"].replace("'", '"'))
            line["coords"] = GEOSGeometry(f"{line['coords']}")
            department_map[current_dpt].append(City(**line))
    cities = sum(department_map.values(), [])
    return City.objects.bulk_create(cities)


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


def create_city_geispolsheim():
    return City.objects.create(
        name="Geispolsheim",
        slug="geispolsheim-67",
        department="67",
        coords=Point(7.644817, 48.515883),
        post_codes=["67118"],
        code_insee="67152",
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
