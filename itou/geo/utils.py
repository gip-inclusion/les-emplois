import logging
import math

from django.contrib.gis.geos import GEOSGeometry


logger = logging.getLogger(__name__)


MAX_DISTANCE_FROM_EARTH_CIRCUMFERENCE = math.ceil(40_075_017 / 2 / 1_000)


def coords_to_geometry(lat, lon) -> GEOSGeometry | None:
    if lat is not None and lon is not None:
        return GEOSGeometry(f"POINT({lon} {lat})")
    return None


def distance_in_km(geo1: GEOSGeometry, geo2: GEOSGeometry) -> float:
    if geo1.srid != geo2.srid:
        raise ValueError(f"Geometry's SRID must be identical, got {[geo1.srid, geo2.srid]}")

    distance = geo1.distance(geo2)
    match geo1.srid:
        case 4326:  # WGS 84
            # The SRID 4326 (WGS 84) return the distance as degree so approximate to 111km.
            # See here: https://stackoverflow.com/a/8477438
            return distance * 111
        case _:
            raise RuntimeError(f"SRID {geo1.srid} not supported")


def multipolygon_to_geometry(spec: str) -> GEOSGeometry:
    return GEOSGeometry(f"{spec}")
