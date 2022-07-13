import logging

from django.contrib.gis.db import models as gis_models
from django.contrib.gis.geos import GEOSGeometry
from django.core.exceptions import ValidationError
from django.db import models

from itou.common_apps.address.departments import DEPARTMENTS, REGIONS, department_from_postcode
from itou.utils.apis.geocoding import GeocodingDataException, get_geocoding_data
from itou.utils.validators import validate_post_code


logger = logging.getLogger(__name__)


def lat_lon_to_coords(lat, lon):
    if lat is not None and lon is not None:
        return GEOSGeometry(f"POINT({lon} {lat})")
    return None


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
    # This score is arbitrarily set based on general observation.
    API_BAN_RELIABLE_MIN_SCORE = 0.4

    DEPARTMENT_CHOICES = DEPARTMENTS.items()

    address_line_1 = models.CharField(verbose_name="Adresse", max_length=255, blank=True)
    address_line_2 = models.CharField(
        verbose_name="Complément d'adresse",
        max_length=255,
        blank=True,
        help_text="Appartement, suite, bloc, bâtiment, boite postale, etc.",
    )
    post_code = models.CharField(verbose_name="Code Postal", validators=[validate_post_code], max_length=5, blank=True)
    city = models.CharField(verbose_name="Ville", max_length=255, blank=True)
    department = models.CharField(
        verbose_name="Département", choices=DEPARTMENT_CHOICES, max_length=3, blank=True, db_index=True
    )
    # Latitude and longitude coordinates.
    # https://docs.djangoproject.com/en/2.2/ref/contrib/gis/model-api/#pointfield
    coords = gis_models.PointField(geography=True, null=True, blank=True)
    # BAN API score between 0 and 1 indicating the relevance of the geocoding result.
    geocoding_score = models.FloatField(verbose_name="Score du geocoding", blank=True, null=True)

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
    def has_reliable_coords(self):
        if not self.geocoding_score:
            return False
        return self.geocoding_score >= self.API_BAN_RELIABLE_MIN_SCORE

    @property
    def address_on_one_line(self):
        if not all([self.address_line_1, self.post_code, self.city]):
            return None
        fields = [self.address_line_1, self.address_line_2, f"{self.post_code} {self.city}"]
        return ", ".join([field for field in fields if field])

    @property
    def geocoding_address(self):
        """
        Using `address_on_one_line` field for geocoding can lead to poor scores
        (because of `address_line_2` field).
        - use `address_on_one_line` for display
        - use `geocoding_address` for geocoding process
        """
        if not all([self.address_line_1, self.post_code, self.city]):
            return None
        fields = [self.address_line_1, f"{self.post_code} {self.city}"]
        return ", ".join([field for field in fields if field])

    def set_coords(self, address, post_code=None):
        try:
            geocoding_data = get_geocoding_data(address, post_code=post_code)
            self.coords = geocoding_data["coords"]
            self.geocoding_score = geocoding_data["score"]
        except GeocodingDataException as exc:
            # The coordinates are not erased because they are used in the search engine,
            # even if they no longer correspond to the address.
            logger.error("No geocoding data could be found for `%s - %s`", address, post_code)
            raise GeocodingDataException(
                f"L'adresse '{ address }' - { post_code } n'a pas été trouvée dans la Base Adresse Nationale."
            ) from exc

    def clean(self):
        if self.department != department_from_postcode(self.post_code):
            raise ValidationError("Le département doit correspondre au code postal.")

        super().clean()
