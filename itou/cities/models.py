from django.contrib.gis.db import models as gis_models
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.db import models

from itou.common_apps.address.departments import DEPARTMENTS, REGIONS


class EditionModeChoices(models.TextChoices):
    AUTO = "AUTO", "Ville mise à jour automatiquement via script"
    MANUAL = "MANUAL", "Ville mise à jour manuellement"


class City(models.Model):
    """
    French cities with geocoding data.
    Raw data is generated via `django-admin generate_cities`
    and then imported into DB via `django-admin import_cities`.
    """

    DEPARTMENT_CHOICES = DEPARTMENTS.items()

    name = models.CharField(verbose_name="Ville", max_length=255, db_index=True)
    slug = models.SlugField(verbose_name="Slug", max_length=255, unique=True)
    department = models.CharField(verbose_name="Département", choices=DEPARTMENT_CHOICES, max_length=3, db_index=True)
    post_codes = ArrayField(models.CharField(max_length=5), verbose_name="Codes postaux", blank=True)
    code_insee = models.CharField(verbose_name="Code INSEE", max_length=5, unique=True)
    # Latitude and longitude coordinates.
    # https://docs.djangoproject.com/en/2.2/ref/contrib/gis/model-api/#pointfield
    coords = gis_models.PointField(geography=True, blank=True, null=True)

    edition_mode = models.CharField(
        verbose_name="Mode d'édition",
        choices=EditionModeChoices.choices,
        max_length=16,
        default=EditionModeChoices.MANUAL,
    )

    objects = models.Manager()  # The default manager.

    class Meta:
        verbose_name = "Ville française"
        verbose_name_plural = "Villes françaises"
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
