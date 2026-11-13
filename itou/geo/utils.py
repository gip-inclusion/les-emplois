import logging
import math

from django.contrib.gis.geos import GEOSGeometry


logger = logging.getLogger(__name__)


MAX_DISTANCE_FROM_EARTH_CIRCUMFERENCE = math.ceil(40_075_017 / 2 / 1_000)


def coords_to_geometry(lat, lon) -> GEOSGeometry | None:
    if lat is not None and lon is not None:
        return GEOSGeometry(f"POINT({lon} {lat})")
    return None


def multipolygon_to_geometry(spec: str) -> GEOSGeometry:
    return GEOSGeometry(f"{spec}")
