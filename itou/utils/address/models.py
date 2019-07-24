import requests
import urllib.parse

from django.contrib.gis.db import models as gis_models
from django.contrib.gis.geos import GEOSGeometry
from django.db import models
from django.utils.translation import gettext_lazy as _


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

    address_line_1 = models.CharField(verbose_name=_("Adresse postale, bôite postale"), max_length=256)
    address_line_2 = models.CharField(verbose_name=_("Appartement, suite, bloc, bâtiment, etc."),
        max_length=256, blank=True)
    zipcode = models.CharField(verbose_name=_("Code Postal"), max_length=10)
    city = models.CharField(verbose_name=_("Ville"), max_length=256)

    # Latitude and longitude coordinates.
    # https://docs.djangoproject.com/en/2.2/ref/contrib/gis/model-api/#pointfield
    coords = gis_models.PointField(geography=True, null=True, blank=True)

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

    def set_coords(self):
        """
        Convert address to latitude/longitude using adresse.data.gouv.fr:
        https://adresse.data.gouv.fr/api
        https://adresse.data.gouv.fr/faq/
        """
        full_address = f"{self.address_line_1} {self.address_line_2} {self.zipcode} {self.city}"
        full_address = ' '.join(full_address.split())
        full_address = urllib.parse.quote_plus(full_address)
        r = requests.get(f"https://api-adresse.data.gouv.fr/search/?q={full_address}&limit=1")
        if r.status_code == 200:
            result = r.json()['features'][0]
            longitude = result['geometry']['coordinates'][0]
            latitude = result['geometry']['coordinates'][1]
            self.coords = GEOSGeometry(f"POINT({longitude} {latitude})")
            self.save()
        # TODO: handle errors.
