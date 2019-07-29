import logging

import requests

from django.conf import settings
from django.contrib.gis.db import models as gis_models
from django.contrib.gis.geos import GEOSGeometry
from django.db import models
from django.utils.http import urlencode

from django.utils.translation import gettext_lazy as _

from itou.utils.address.departments import DEPARTMENTS, REGIONS


logger = logging.getLogger(__name__)


class AddressMixin(models.Model):
    """
    Designing an Address model is tricky.
    So let's just keep it as simple as possible.
    We'll use a parser if the need arises.

    Some reading on the subject.
    https://www.mjt.me.uk/posts/falsehoods-programmers-believe-about-addresses/
    https://machinelearnings.co/statistical-nlp-on-openstreetmap-b9d573e6cc86
    https://github.com/openvenues/libpostal
    https://github.com/openvenues/pypostal

    Assume that all addresses are in France. This is unlikely to change.
    """

    # Below this score, results from `adresse.data.gouv.fr` are considered unreliable.
    # This score is arbitrarily set based on general observation in the `import_siae` command.
    API_BAN_RELIABLE_MIN_SCORE = 0.6

    DEPARTMENT_CHOICES = DEPARTMENTS.items()

    address_line_1 = models.CharField(verbose_name=_("Adresse postale, bôite postale"), max_length=256, blank=True)
    address_line_2 = models.CharField(verbose_name=_("Appartement, suite, bloc, bâtiment, etc."),
        max_length=256, blank=True)
    zipcode = models.CharField(verbose_name=_("Code Postal"), max_length=10, blank=True)
    city = models.CharField(verbose_name=_("Ville"), max_length=256, blank=True)
    department = models.CharField(verbose_name=_("Département"), choices=DEPARTMENT_CHOICES, max_length=3, blank=True)
    # Latitude and longitude coordinates.
    # https://docs.djangoproject.com/en/2.2/ref/contrib/gis/model-api/#pointfield
    coords = gis_models.PointField(geography=True, null=True, blank=True)
    # Score between 0 and 1 indicating the relevance of the geocoding result.
    # If greater than API_BAN_RELIABLE_MIN_SCORE, coords are reliable.
    geocoding_score = models.FloatField(verbose_name=_("Score du geocoding"), blank=True, null=True)

    class Meta:
        abstract = True

    @property
    def latitude(self):
        if self.coords:
            return self.coords.y
        return None

    @property
    def longitude(self):
        if self.coords:
            return self.coords.x
        return None

    @property
    def region(self):
        if self.department:
            for region, departments in REGIONS.items():
                if self.department in departments:
                    return region
        return None

    @property
    def full_address_on_one_line(self):
        if not all([self.address_line_1, self.zipcode, self.city]):
            return None
        fields = [
            self.address_line_1,
            self.address_line_2,
            f"{self.zipcode} {self.city}",
        ]
        return ', '.join([field for field in fields if field])

    def set_coords(self):
        """
        Transform a French physical address description to longitude/latitude coordinates.
        https://adresse.data.gouv.fr/api
        https://adresse.data.gouv.fr/faq
        """
        api_url = f"{settings.API_BAN_BASE_URL}/search/"
        query_string = urlencode({'q': self.full_address_on_one_line, 'limit': 1})

        r = requests.get(f"{api_url}?{query_string}")
        r.raise_for_status()

        try:
            result = r.json()['features'][0]
            longitude = result['geometry']['coordinates'][0]
            latitude = result['geometry']['coordinates'][1]
            self.coords = GEOSGeometry(f"POINT({longitude} {latitude})")
            self.save()
        except IndexError:
            logger.error(f"Geocoding error, no result for SIRET {self.siret}")
