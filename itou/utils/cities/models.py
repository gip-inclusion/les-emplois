from django.conf import settings
from django.contrib.gis.db import models as gis_models
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils.translation import gettext_lazy as _

from itou.utils.address.departments import DEPARTMENTS, REGIONS


class City(models.Model):
    """
    French cities with geocoding data.
    Raw data is generated via `django-admin generate_cities_file`
    and then imported into DB via `django-admin import_cities`.
    """

    DEPARTMENT_CHOICES = DEPARTMENTS.items()

    name = models.CharField(verbose_name=_("Ville"), max_length=256, db_index=True)
    slug = models.SlugField(verbose_name=_("Slug"), max_length=256, db_index=True)
    # Can be empty.
    # https://fr.wikipedia.org/wiki/Saint-Pierre-et-Miquelon#Statut
    department = models.CharField(verbose_name=_("Département"), choices=DEPARTMENT_CHOICES, max_length=3, blank=True)
    post_codes = ArrayField(models.CharField(max_length=5), verbose_name=_("Codes postaux"), blank=True)
    code_insee = models.CharField(verbose_name=_("Code INSEE"), max_length=5)
    # Latitude and longitude coordinates.
    # https://docs.djangoproject.com/en/2.2/ref/contrib/gis/model-api/#pointfield
    coords = gis_models.PointField(geography=True, blank=True, null=True)

    class Meta:
        verbose_name = _("Ville française")
        verbose_name_plural = _("Villes françaises")

    def __str__(self):
        return f"{self.name}"

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
