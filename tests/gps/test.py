from django.core.cache import cache

from itou.gps.utils import GPS_ADVISORS_KEY, FranceTravailContactDetails


def mock_advisor_list(nir):
    cache.set(GPS_ADVISORS_KEY, {nir: FranceTravailContactDetails("Jean BON", "jean.bon@francetravail.fr")})
