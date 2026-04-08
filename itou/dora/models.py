from django.contrib.gis.db import models as gis_models
from django.db import models

from itou.utils.validators import validate_post_code


SOURCE_DORA_VALUE = "dora"


class GeolocatedAddressMixin(models.Model):
    address_line_1 = models.CharField(verbose_name="adresse", blank=True)
    address_line_2 = models.CharField(
        verbose_name="complément d'adresse",
        blank=True,
        help_text="Appartement, suite, bloc, bâtiment, boite postale, etc.",
    )
    post_code = models.CharField(
        verbose_name="code postal",
        validators=[validate_post_code],
        max_length=5,
        blank=True,
    )
    city = models.CharField(verbose_name="ville", blank=True)
    insee_city = models.ForeignKey("cities.City", on_delete=models.RESTRICT, null=True)

    coordinates = gis_models.PointField(geography=True, null=True, blank=True)

    class Meta:
        abstract = True


class ReferenceDatumKind(models.TextChoices):
    FEE = "FEE", "Frais"
    RECEPTION = "RECEPTION", "Mode d'accueil"
    MOBILIZATION = "MOBILIZATION", "Mode de mobilisation"
    MOBILIZATION_PUBLIC = "MOBILIZATION_PUBLIC", "Personne mobilisatrices"
    PUBLIC = "PUBLIC", "Public"
    NETWORK = "NETWORK", "Réseau porteur"
    THEMATIC = "THEMATIC", "Thématique"
    SERVICE_KIND = "SERVICE_KIND", "Type de service"
    SOURCE = "SOURCE", "Source"


class ReferenceDatum(models.Model):
    kind = models.CharField(choices=ReferenceDatumKind.choices)
    value = models.CharField(verbose_name="valeur")
    label = models.CharField()
    description = models.TextField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["kind", "value"], name="unique_value_for_kind"),
        ]


class Structure(GeolocatedAddressMixin, models.Model):
    uid = models.CharField(unique=True)

    source = models.ForeignKey(
        ReferenceDatum,
        on_delete=models.RESTRICT,
        limit_choices_to={"kind": ReferenceDatumKind.SOURCE},
        related_name="+",
    )

    siret = models.CharField(blank=True)

    name = models.CharField()
    description = models.TextField(blank=True)
    website = models.URLField(verbose_name="site web", max_length=512, blank=True)

    email = models.EmailField(verbose_name="e-mail", blank=True)
    phone = models.CharField(verbose_name="téléphone", max_length=20, blank=True)

    updated_on = models.DateField()


class Service(GeolocatedAddressMixin, models.Model):
    uid = models.CharField(unique=True)

    source = models.ForeignKey(
        ReferenceDatum,
        on_delete=models.RESTRICT,
        limit_choices_to={"kind": ReferenceDatumKind.SOURCE},
        related_name="+",
    )
    source_link = models.URLField(blank=True, max_length=512)

    structure = models.ForeignKey(Structure, on_delete=models.CASCADE)

    name = models.CharField()
    description = models.TextField()
    description_short = models.TextField(blank=True)

    kind = models.ForeignKey(
        ReferenceDatum,
        on_delete=models.RESTRICT,
        limit_choices_to={"kind": ReferenceDatumKind.SERVICE_KIND},
        null=True,
        related_name="+",
    )

    thematics = models.ManyToManyField(
        ReferenceDatum,
        limit_choices_to={"kind": ReferenceDatumKind.THEMATIC},
        related_name="+",
    )

    fee = models.ForeignKey(
        ReferenceDatum,
        on_delete=models.RESTRICT,
        limit_choices_to={"kind": ReferenceDatumKind.FEE},
        null=True,
        related_name="+",
    )
    fee_details = models.TextField(blank=True)

    publics = models.ManyToManyField(
        ReferenceDatum,
        limit_choices_to={"kind": ReferenceDatumKind.PUBLIC},
        related_name="+",
    )
    publics_details = models.TextField(blank=True)

    access_conditions = models.TextField(blank=True)

    receptions = models.ManyToManyField(
        ReferenceDatum,
        limit_choices_to={"kind": ReferenceDatumKind.RECEPTION},
        related_name="+",
    )

    mobilizations = models.ManyToManyField(
        ReferenceDatum,
        limit_choices_to={"kind": ReferenceDatumKind.MOBILIZATION},
        related_name="+",
    )
    mobilizations_details = models.TextField(blank=True)
    mobilization_publics = models.ManyToManyField(
        ReferenceDatum,
        limit_choices_to={"kind": ReferenceDatumKind.MOBILIZATION_PUBLIC},
        related_name="+",
    )
    mobilization_link = models.URLField(blank=True, max_length=512)

    opening_hours = models.CharField(verbose_name="horaires d'accueil", blank=True)

    contact_full_name = models.CharField(blank=True)
    contact_email = models.EmailField(verbose_name="e-mail", blank=True)
    contact_phone = models.CharField(verbose_name="téléphone", max_length=20, blank=True)

    is_orientable_with_form = models.BooleanField(default=True)
    average_orientation_response_delay_days = models.PositiveIntegerField(null=True)

    updated_on = models.DateField()
