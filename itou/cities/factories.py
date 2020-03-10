import json
import os

from django.contrib.gis.geos import GEOSGeometry
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
        create_test_cities(settings.ITOU_TEST_DEPARTMENTS, num_per_department=10)
    """
    departments_counter = {department: 0 for department in selected_departments}

    with open(CITIES_JSON_FILE, "r") as raw_json_data:

        json_data = json.load(raw_json_data)

        for item in json_data:

            department = item.get("codeDepartement")
            if (not department) or (department not in selected_departments):
                continue

            coords = item.get("centre")
            if not coords:
                continue

            departments_counter[department] += 1
            if (
                num_per_department
                and departments_counter[department] > num_per_department
            ):
                if all(
                    value >= num_per_department
                    for value in departments_counter.values()
                ):
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
