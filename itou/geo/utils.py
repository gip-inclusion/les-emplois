from typing import Optional

from django.contrib.gis.geos import GEOSGeometry


def coords_to_geometry(lat, lon) -> Optional[GEOSGeometry]:
    if lat is not None and lon is not None:
        return GEOSGeometry(f"POINT({lon} {lat})")
    return None


def multipolygon_to_geometry(spec: str) -> GEOSGeometry:
    return GEOSGeometry(f"{spec}")
