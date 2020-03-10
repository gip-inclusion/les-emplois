import logging

from django.contrib.gis.db import models as gis_models
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from itou.utils.address.departments import DEPARTMENTS, REGIONS
from itou.utils.apis.geocoding import get_geocoding_data
from itou.utils.validators import validate_post_code

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
    # This score is arbitrarily set based on general observation.
    API_BAN_RELIABLE_MIN_SCORE = 0.4

    DEPARTMENT_CHOICES = DEPARTMENTS.items()

    address_line_1 = models.CharField(
        verbose_name=gettext_lazy("Adresse"), max_length=255, blank=True
    )
    address_line_2 = models.CharField(
        verbose_name=gettext_lazy("Complément d'adresse"),
        max_length=255,
        blank=True,
        help_text=gettext_lazy(
            "Appartement, suite, bloc, bâtiment, boite postale, etc."
        ),
    )
    post_code = models.CharField(
        verbose_name=gettext_lazy("Code Postal"),
        validators=[validate_post_code],
        max_length=5,
        blank=True,
    )
    city = models.CharField(
        verbose_name=gettext_lazy("Ville"), max_length=255, blank=True
    )
    department = models.CharField(
        verbose_name=gettext_lazy("Département"),
        choices=DEPARTMENT_CHOICES,
        max_length=3,
        blank=True,
    )
    # Latitude and longitude coordinates.
    # https://docs.djangoproject.com/en/2.2/ref/contrib/gis/model-api/#pointfield
    coords = gis_models.PointField(geography=True, null=True, blank=True)
    # BAN API score between 0 and 1 indicating the relevance of the geocoding result.
    geocoding_score = models.FloatField(
        verbose_name=gettext_lazy("Score du geocoding"), blank=True, null=True
    )

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
        fields = [
            self.address_line_1,
            self.address_line_2,
            f"{self.post_code} {self.city}",
        ]
        return ", ".join([field for field in fields if field])

    def set_coords(self, address, post_code=None):
        geocoding_data = get_geocoding_data(address, post_code=post_code)
        if not geocoding_data:
            logger.error(
                "No geocoding data could be found for `%s - %s`", address, post_code
            )
            return
        self.coords = geocoding_data["coords"]
        self.geocoding_score = geocoding_data["score"]

    def set_coords_and_address(self, address, post_code=None):
        geocoding_data = get_geocoding_data(address, post_code=post_code)
        if not geocoding_data:
            logger.error(
                "No geocoding data could be found for `%s - %s`", address, post_code
            )
            return
        self.coords = geocoding_data["coords"]
        self.geocoding_score = geocoding_data["score"]
        self.address_line_1 = geocoding_data["address_line_1"]
        self.address_line_2 = ""
        self.post_code = geocoding_data["post_code"]
        self.city = geocoding_data["city"]

    def clean(self):
        if self.post_code:
            if not self.post_code.startswith(self.department):
                raise ValidationError(
                    _("Le département doit correspondre au code postal.")
                )
        super().clean()
