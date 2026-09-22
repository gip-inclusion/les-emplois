import random

from django.contrib.gis.geos import Point

from itou.www.directory_views.views import DIRECTORY_RADIUS_KM


# https://stackoverflow.com/a/8477438
# 0.01 degree is roughly 1.11 km
KM = 0.01


def coords_within_directory_radius(origin):
    # Increased until the tests no longer failed when run in tight loops.
    tolerance = 0.8
    limit = ((DIRECTORY_RADIUS_KM * tolerance) / 1.11) * KM
    x_dist = limit * random.random() * random.choice([1, -1])
    y_dist = limit * random.random() * random.choice([1, -1])
    return Point(origin.x + x_dist, origin.y + y_dist)
