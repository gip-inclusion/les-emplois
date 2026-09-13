from datetime import timedelta

from django.core.cache import caches

from itou.cities.models import DirectoryActiveCity


CACHE_DIRECTORY_ACTIVE_CITY_IDS_KEY = "directory-active-city-ids"
CACHE_DIRECTORY_ACTIVE_CITIES_TIMEOUT = timedelta(minutes=5).total_seconds()


def get_directory_active_city_ids():
    return caches["failsafe"].get_or_set(
        CACHE_DIRECTORY_ACTIVE_CITY_IDS_KEY,
        lambda: frozenset(DirectoryActiveCity.objects.values_list("city_id", flat=True)),
        CACHE_DIRECTORY_ACTIVE_CITIES_TIMEOUT,
    )
