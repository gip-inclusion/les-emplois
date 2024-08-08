import datetime
import random

from django.contrib.gis.geos import Point
from faker.providers import BaseProvider


class ItouProvider(BaseProvider):
    def asp_batch_filename(self) -> str:
        return f"RIAE_FS_{random.randint(0, 99999999999999)}.json"

    def asp_ea2_filename(self, date: datetime.date = None) -> str:
        date_part = random.randint(0, 99999999) if date is None else date.strftime("%Y%m%d")
        return f"FLUX_EA2_ITOU_{date_part}.zip"

    def geopoint(self) -> Point:
        return Point(
            [float(coord) for coord in self.generator.format("local_latlng", country_code="FR", coords_only=True)]
        )
