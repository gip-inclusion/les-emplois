from django.contrib.gis.db import models as gis_models
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils import timezone

from itou.utils.validators import validate_post_code


SOURCE_DORA_VALUE = "dora"


class GeolocatedAddressMixin(models.Model):
    """Address fields for objects imported from data·inclusion and DORA.

    Deliberately kept separate from `common_apps.address.AddressMixin`: imported objects
    are already geocoded upstream and never go through our BAN geocoding pipeline.
    Reusing `AddressMixin` would pull in unused fields and behaviour (geocoding score,
    department validation, QPV/ZRR lookups…) and couple this import to unrelated business
    logic. A dedicated mixin keeps the `insertion` app independent and free of side
    effects.
    """

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
    insee_city = models.ForeignKey("cities.City", on_delete=models.RESTRICT, null=True, related_name="+")

    coordinates = gis_models.PointField(geography=True, null=True, blank=True)

    @property
    def address_on_one_line(self):
        if not all([self.address_line_1, self.post_code, self.city]):
            return None
        fields = [
            self.address_line_1,
            self.address_line_2,
            f"{self.post_code} {self.city}",
        ]
        return ", ".join(field for field in fields if field)

    class Meta:
        abstract = True


class GenericReferenceItemSource(models.TextChoices):
    DATA_INCLUSION = "DATA_INCLUSION", "data·inclusion"
    DORA = "DORA", "DORA"


class GenericReferenceItemKind(models.TextChoices):
    FEE = "FEE", "Frais"
    FUNDING_LABEL = "FUNDING_LABEL", "Label de financement"
    MOBILIZATION = "MOBILIZATION", "Mode de mobilisation"
    MOBILIZATION_BENEFICIARY = "MOBILIZATION_BENEFICIARY", "Mode de mobilisation bénéficiaires"
    MOBILIZATION_PUBLIC = "MOBILIZATION_PUBLIC", "Personne mobilisatrices"
    MOBILIZATION_PROFESSIONAL = "MOBILIZATION_PROFESSIONAL", "Mode de mobilisation professionnels"
    NETWORK = "NETWORK", "Réseau porteur"
    PUBLIC = "PUBLIC", "Public"
    RECEPTION = "RECEPTION", "Mode d'accueil"
    SERVICE_KIND = "SERVICE_KIND", "Type de service"
    SOURCE = "SOURCE", "Source"
    THEMATIC = "THEMATIC", "Thématique"


class GenericReferenceItem(models.Model):
    source = models.CharField(choices=GenericReferenceItemSource.choices)
    kind = models.CharField(verbose_name="type", choices=GenericReferenceItemKind.choices)
    value = models.CharField(verbose_name="valeur")
    label = models.CharField(verbose_name="libellé")
    description = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now)
    updated_at = models.DateTimeField(verbose_name="date de modification", auto_now=True)

    class Meta:
        verbose_name = "référentiel data·inclusion & DORA"
        verbose_name_plural = "référentiels data·inclusion & DORA"
        constraints = [
            models.UniqueConstraint(fields=["source", "kind", "value"], name="unique_value_for_kind_and_source"),
        ]

    def __str__(self):
        return self.label


class Structure(GeolocatedAddressMixin, models.Model):
    uid = models.CharField(unique=True)

    source = models.ForeignKey(
        to=GenericReferenceItem,
        on_delete=models.RESTRICT,
        limit_choices_to={
            "source": GenericReferenceItemSource.DATA_INCLUSION,
            "kind": GenericReferenceItemKind.SOURCE,
        },
        related_name="+",
    )
    source_link = models.URLField(verbose_name="lien de la source", blank=True, max_length=512)

    siret = models.CharField(blank=True)

    name = models.CharField(verbose_name="nom")
    description = models.TextField(blank=True)
    website = models.URLField(verbose_name="site web", max_length=512, blank=True)

    email = models.EmailField(verbose_name="e-mail", blank=True)
    phone = models.CharField(verbose_name="téléphone", max_length=20, blank=True)

    opening_hours = models.CharField(verbose_name="horaires d'accueil", blank=True)

    updated_on = models.DateField(verbose_name="date de modification data·inclusion")

    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now)
    updated_at = models.DateTimeField(verbose_name="date de modification", auto_now=True)

    class Meta:
        verbose_name = "structure d'insertion"
        verbose_name_plural = "structures d'insertion"

    def __str__(self):
        return self.uid


class Service(GeolocatedAddressMixin, models.Model):
    uid = models.CharField(unique=True)

    source = models.ForeignKey(
        to=GenericReferenceItem,
        on_delete=models.RESTRICT,
        limit_choices_to={
            "source": GenericReferenceItemSource.DATA_INCLUSION,
            "kind": GenericReferenceItemKind.SOURCE,
        },
        related_name="+",
    )
    source_link = models.URLField(verbose_name="lien vers la source", blank=True, max_length=512)

    structure = models.ForeignKey(Structure, on_delete=models.CASCADE, related_name="services")

    name = models.CharField(verbose_name="nom")
    description = models.TextField(verbose_name="description complète")
    description_short = models.TextField(verbose_name="description courte", blank=True)

    kind = models.ForeignKey(
        verbose_name="type de service",
        to=GenericReferenceItem,
        on_delete=models.RESTRICT,
        limit_choices_to={
            "source": GenericReferenceItemSource.DATA_INCLUSION,
            "kind": GenericReferenceItemKind.SERVICE_KIND,
        },
        null=True,
        related_name="+",
    )

    thematics = models.ManyToManyField(
        verbose_name="thématiques",
        to=GenericReferenceItem,
        limit_choices_to={
            "source": GenericReferenceItemSource.DATA_INCLUSION,
            "kind": GenericReferenceItemKind.THEMATIC,
        },
        related_name="+",
    )

    fee = models.ForeignKey(
        verbose_name="frais",
        to=GenericReferenceItem,
        on_delete=models.RESTRICT,
        limit_choices_to={"source": GenericReferenceItemSource.DATA_INCLUSION, "kind": GenericReferenceItemKind.FEE},
        null=True,
        related_name="+",
    )
    fee_details = models.TextField(verbose_name="frais - précisions", blank=True)

    publics = models.ManyToManyField(
        verbose_name="publics visés",
        to=GenericReferenceItem,
        limit_choices_to={
            "source": GenericReferenceItemSource.DATA_INCLUSION,
            "kind": GenericReferenceItemKind.PUBLIC,
        },
        related_name="+",
    )
    publics_details = models.TextField(verbose_name="publics visés - précisions", blank=True)

    access_conditions_di = models.TextField(verbose_name="critères d’admission (data·inclusion)", blank=True)
    access_conditions_dora = ArrayField(
        verbose_name="critères d’admission (DORA)",
        base_field=models.CharField(),
        default=list,
        blank=True,
    )

    eligibility_zones = ArrayField(
        verbose_name="zones d’éligibilité",
        base_field=models.CharField(),
        default=list,
        blank=True,
    )

    receptions = models.ManyToManyField(
        verbose_name="modes d'accueil",
        to=GenericReferenceItem,
        limit_choices_to={
            "source": GenericReferenceItemSource.DATA_INCLUSION,
            "kind": GenericReferenceItemKind.RECEPTION,
        },
        related_name="+",
    )

    # data·inclusion's mobilization fields
    mobilizations = models.ManyToManyField(
        verbose_name="modes de mobilisation",
        to=GenericReferenceItem,
        limit_choices_to={
            "source": GenericReferenceItemSource.DATA_INCLUSION,
            "kind": GenericReferenceItemKind.MOBILIZATION,
        },
        related_name="+",
    )
    mobilizations_details = models.TextField(verbose_name="modes de mobilisation - précisions", blank=True)
    mobilization_publics = models.ManyToManyField(
        verbose_name="personne mobilisatrices",
        to=GenericReferenceItem,
        limit_choices_to={
            "source": GenericReferenceItemSource.DATA_INCLUSION,
            "kind": GenericReferenceItemKind.MOBILIZATION_PUBLIC,
        },
        related_name="+",
    )

    # DORA's mobilization fields
    mobilization_modes_beneficiaries = models.ManyToManyField(
        verbose_name="comment mobiliser la solution en tant que bénéficiaire",
        to=GenericReferenceItem,
        limit_choices_to={
            "source": GenericReferenceItemSource.DORA,
            "kind": GenericReferenceItemKind.MOBILIZATION_BENEFICIARY,
        },
        related_name="+",
    )
    mobilization_modes_beneficiaries_external_form_link = models.URLField(
        verbose_name="lien vers le formulaire externe", blank=True
    )
    mobilization_modes_beneficiaries_external_form_link_text = models.CharField(
        verbose_name="l’intitulé du lien vers le formulaire externe",
        blank=True,
    )
    mobilization_modes_beneficiaries_other = models.CharField(verbose_name="autre", blank=True)
    mobilization_modes_professionals = models.ManyToManyField(
        verbose_name="comment orienter un bénéficiaire en tant qu’accompagnateur",
        to=GenericReferenceItem,
        limit_choices_to={
            "source": GenericReferenceItemSource.DORA,
            "kind": GenericReferenceItemKind.MOBILIZATION_PROFESSIONAL,
        },
        related_name="+",
    )
    mobilization_modes_professionals_external_form_link = models.URLField(
        verbose_name="lien vers le formulaire externe", blank=True
    )
    mobilization_modes_professionals_external_form_link_text = models.CharField(
        verbose_name="l’intitulé du lien vers le formulaire externe",
        blank=True,
    )
    mobilization_modes_professionals_other = models.CharField(verbose_name="autre", blank=True)

    credentials = ArrayField(
        verbose_name="justificatifs à fournir",
        base_field=models.CharField(),
        default=list,
        blank=True,
    )
    credentials_documents = ArrayField(
        verbose_name="documents justificatifs à compléter",
        base_field=models.CharField(max_length=1024),  # See File().key for `max_length` rational
        default=list,
        blank=True,
    )
    credentials_online_form = models.URLField(
        verbose_name="formulaire en ligne à compléter",
        blank=True,
        # No `max_length` to use Django's default just like DORA
    )

    funding_labels = models.ManyToManyField(
        verbose_name="labels de financement",
        to=GenericReferenceItem,
        limit_choices_to={"source": GenericReferenceItemSource.DORA, "kind": GenericReferenceItemKind.FUNDING_LABEL},
        related_name="+",
    )

    opening_hours = models.CharField(verbose_name="horaires d'accueil", blank=True)
    opening_hours_text = models.CharField(verbose_name="horaires d'accueil (texte libre)", blank=True)

    contact_full_name = models.CharField(verbose_name="contact", blank=True)
    contact_email = models.EmailField(verbose_name="e-mail du contact", blank=True)
    contact_phone = models.CharField(verbose_name="téléphone du contact", max_length=20, blank=True)
    contact_is_public = models.BooleanField(verbose_name="informations du contact publiques", default=True)

    is_orientable_with_form = models.BooleanField(verbose_name="formulaire d'orientation actif", default=True)
    average_orientation_response_delay_days = models.PositiveIntegerField(
        verbose_name="temps moyen de réponse aux orientations (jour)", null=True
    )

    dora_synced_at = models.DateTimeField(verbose_name="date de synchronisation DORA", null=True, blank=True)

    updated_on = models.DateField(verbose_name="date de modification data·inclusion")

    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now)
    updated_at = models.DateTimeField(verbose_name="date de modification", auto_now=True)

    class Meta:
        verbose_name = "service d'insertion"
        verbose_name_plural = "services d'insertion"

    def __str__(self):
        return self.uid
