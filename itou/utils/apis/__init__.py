from django.conf import settings

from .pole_emploi import PoleEmploiApiClient


# Values updated in review app's environment to communicate with
# PE's pre-production servers.
def pole_emploi_api_client():
    return PoleEmploiApiClient(
        settings.API_ESD["BASE_URL"],
        settings.API_ESD["AUTH_BASE_URL"],
        settings.API_ESD["KEY"],
        settings.API_ESD["SECRET"],
    )
