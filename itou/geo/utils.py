import logging

from django.contrib.gis.db.models import PointField
from django.contrib.gis.geos import GEOSGeometry
from django.db import models
from django.db.models.functions import Cast


logger = logging.getLogger(__name__)


def lat_lon_to_geometry(lat: float, lon: float) -> GEOSGeometry | None:
    """Converts latitude, longitude tuple to postgis geometry"""
    if lat is not None and lon is not None:
        return GEOSGeometry(f"POINT({lon} {lat})")
    return None


def multipolygon_to_geometry(spec: str) -> GEOSGeometry:
    return GEOSGeometry(f"{spec}")


class GeoUtilsQueryset(models.QuerySet):
    def to_geom(self, geography_name="coords"):
        # Annotate a *geography* field with a `geom` field which is a *geometry*
        # thus becoming usable for spatial joins
        return self.annotate(geom=Cast(geography_name, PointField()))
