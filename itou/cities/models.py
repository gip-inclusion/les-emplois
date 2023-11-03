from django.contrib.gis.db import models as gis_models
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.db import models

from itou.common_apps.address.departments import DEPARTMENTS, REGIONS


class EditionModeChoices(models.TextChoices):
    AUTO = "AUTO", "Ville mise à jour automatiquement via script"
    MANUAL = "MANUAL", "Ville mise à jour manuellement"


class City(models.Model):
    """French cities with their geocoding data, synchronized via the sync_cities script regularly."""

    DEPARTMENT_CHOICES = DEPARTMENTS.items()

    name = models.CharField(verbose_name="ville", max_length=255, db_index=True)
    slug = models.SlugField(verbose_name="slug", max_length=255, unique=True)
    department = models.CharField(verbose_name="département", choices=DEPARTMENT_CHOICES, max_length=3, db_index=True)

    # Note that post codes and insee codes have a n-to-n relationship.
    # One insee code can have several post codes but the inverse is also true e.g. zip code 33360 has six insee codes.
    post_codes = ArrayField(models.CharField(max_length=5), verbose_name="codes postaux", blank=True)
    code_insee = models.CharField(verbose_name="code INSEE", max_length=5, unique=True)

    # Latitude and longitude coordinates.
    # https://docs.djangoproject.com/en/2.2/ref/contrib/gis/model-api/#pointfield
    coords = gis_models.PointField(geography=True, blank=True, null=True)

    edition_mode = models.CharField(
        verbose_name="mode d'édition",
        choices=EditionModeChoices.choices,
        max_length=16,
        default=EditionModeChoices.MANUAL,
    )

    objects = models.Manager()  # The default manager.

    class Meta:
        verbose_name = "ville française"
        verbose_name_plural = "villes françaises"
        indexes = [
            # https://docs.djangoproject.com/en/dev/ref/contrib/postgres/search/#trigram-similarity
            # https://docs.djangoproject.com/en/dev/ref/contrib/postgres/indexes/#ginindex
            # https://www.postgresql.org/docs/11/pgtrgm.html#id-1.11.7.40.7
            GinIndex(fields=["name"], name="cities_city_name_gin_trgm", opclasses=["gin_trgm_ops"])
        ]

    def __str__(self):
        return self.display_name

    def save(self, *args, **kwargs):
        # Any save() forces the edition_mode to be MANUAL. Only the sync_cities script
        # can take care of forcing the mode to AUTO.
        self.edition_mode = EditionModeChoices.MANUAL
        super().save(*args, **kwargs)

    @property
    def display_name(self):
        return f"{self.name} ({self.department})"

    def autocomplete_display(self):
        return self.display_name

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
