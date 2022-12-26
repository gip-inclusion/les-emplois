import logging

from django.contrib.gis.geos import GEOSGeometry


logger = logging.getLogger(__name__)


def coords_to_geometry(lat, lon) -> GEOSGeometry | None:
    if lat is not None and lon is not None:
        return GEOSGeometry(f"POINT({lon} {lat})")
    return None


def multipolygon_to_geometry(spec: str) -> GEOSGeometry:
    return GEOSGeometry(f"{spec}")
