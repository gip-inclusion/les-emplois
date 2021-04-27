from faker.providers import BaseProvider

from itou.asp.models import Commune, Country


class INSEECommuneProvider(BaseProvider):
    """
    Provides a random INSEE Commune
    Uses fixtures / DB
    Mainly used for user / job seeker birth place
    """

    def asp_insee_commune(self):
        return Commune.objects.all().order_by("?").first()


class INSEECountryProvider(BaseProvider):
    """
    Provides a random INSEE Country
    Uses fixtures / DB
    Mainly used for user / job seeker birth country
    """

    def asp_country(self):
        return Country.objects.all().order_by("?").first()
