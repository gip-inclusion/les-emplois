import random

from django.contrib.gis.geos import Point
from faker.providers import BaseProvider


class ItouProvider(BaseProvider):
    def asp_batch_filename(self) -> str:
        return f"RIAE_FS_{random.randint(0, 99999999999999)}.json"

    def geopoint(self) -> Point:
        return Point(
            [float(coord) for coord in self.generator.format("local_latlng", country_code="FR", coords_only=True)]
        )
