import httpx
from django.conf import settings


##
# Utility functions
##


def get_probes_classes():
    classes = {
        BaseAdresseNationaleApiProbe,
        GeoApiProbe,
        EntrepriseApiProbe,
        EmploiStoreDevAuthApiProbe,
        EmploiStoreDevApiProbe,
        MailjetApiProbe,
        PoleEmploiAccessManagementUserAuthProbe,
    }
    if settings.FRANCE_CONNECT_BASE_URL:
        classes.add(FranceConnectAuthProbe)

    return classes


##
# Base probes classes
##


class Probe:
    name = None
    verbose_name = None

    def check(self):
        raise NotImplementedError


class HttpProbe(Probe):
    url = None

    def check(self):
        if not self.url:
            raise RuntimeError(f"Empty 'url' for {self.__class__.__name__}")

        r = httpx.head(self.url)
        return not r.is_server_error, str(r)


##
# Probes for API
##


class BaseAdresseNationaleApiProbe(HttpProbe):
    name = "api.ban"
    verbose_name = "BAN API"
    url = settings.API_BAN_BASE_URL


class GeoApiProbe(HttpProbe):
    name = "api.geo"
    verbose_name = "Geo API"
    url = settings.API_BAN_BASE_URL


class EntrepriseApiProbe(HttpProbe):
    name = "api.entreprise"
    verbose_name = "Entreprise API"
    url = settings.API_INSEE_SIRENE_BASE_URL


class EmploiStoreDevAuthApiProbe(HttpProbe):
    name = "api.esd_auth"
    verbose_name = "ESD Auth API"
    url = settings.API_ESD.get("AUTH_BASE_URL")


class EmploiStoreDevApiProbe(HttpProbe):
    name = "api.esd"
    verbose_name = "ESD API"
    url = settings.API_ESD.get("BASE_URL")


class MailjetApiProbe(HttpProbe):
    name = "api.mailjet"
    verbose_name = "Mailjet API"
    url = settings.ANYMAIL["MAILJET_API_URL"]


##
# Probes for Auth providers
##


class PoleEmploiAccessManagementUserAuthProbe(HttpProbe):
    name = "auth.peamu"
    verbose_name = "PEAM-U"
    url = settings.PEAMU_AUTH_BASE_URL


class FranceConnectAuthProbe(HttpProbe):
    name = "auth.fc"
    verbose_name = "France Connect"
    url = settings.FRANCE_CONNECT_BASE_URL
