from django.conf import settings
from django.contrib.gis.db import models as gis_models
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils.translation import gettext_lazy as _


class City(models.Model):
    """
    French cities
    """

    name = models.CharField(verbose_name=_("Ville"), max_length=256)
    department = models.CharField(verbose_name=_("Numéro du département"), max_length=3, blank=True)
    post_codes = ArrayField(models.CharField(max_length=5), verbose_name=_("Codes postaux"))
    code_insee = models.CharField(verbose_name=_("Code INSEE"), max_length=5)
    # Latitude and longitude coordinates.
    # https://docs.djangoproject.com/en/2.2/ref/contrib/gis/model-api/#pointfield
    coords = gis_models.PointField(geography=True)

    class Meta:
        verbose_name = _("Ville française")
        verbose_name_plural = _("Villes françaises")

    def __str__(self):
        return f"{self.name}"
