from django.conf import settings

from itou.utils.apis.pole_emploi import PoleEmploiApiClient


def pole_emploi_api_client():
    return PoleEmploiApiClient(
        settings.API_ESD["BASE_URL"],
        settings.API_ESD["AUTH_BASE_URL"],
        settings.API_ESD["KEY"],
        settings.API_ESD["SECRET"],
    )
