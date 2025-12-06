import datetime

from citext import CIEmailField
from django.db import models
from django.db.models import F, OuterRef
from django.db.models.functions import Coalesce

from itou.common_apps.address.models import AddressMixin
from itou.nexus.enums import Auth, NexusStructureKind, NexusUserKind, Role, Service


# Set a default threshold so that we don't have to handle empty thershold for services without a full sync
DEFAULT_THRESHOLD = datetime.datetime(2025, 12, 1, tzinfo=datetime.UTC)


class NexusQuerySet(models.QuerySet):
    def with_threshold(self):
        return self.annotate(
            threshold=Coalesce(
                APIFullSync.objects.filter(service=OuterRef("source")).values("timestamp")[:1],
                DEFAULT_THRESHOLD,
            )
        )


class NexusManager(models.Manager.from_queryset(NexusQuerySet)):
    def get_queryset(self):
        return super().get_queryset().with_threshold().filter(updated_at__gte=F("threshold"))


class NexusUser(models.Model):
    id = models.CharField(verbose_name="ID unique", primary_key=True)  # Built from source and source_id

    source = models.CharField(verbose_name="source de la donnée", choices=Service.choices)
    source_id = models.CharField(verbose_name="ID Source")
    source_kind = models.CharField(verbose_name="type d'origine")

    first_name = models.CharField(verbose_name="prénom")
    last_name = models.CharField(verbose_name="nom")
    email = CIEmailField("adresse e-mail", db_index=True)
    phone = models.CharField(verbose_name="téléphone", max_length=20, blank=True)
    last_login = models.DateTimeField(verbose_name="date de denière connexion")
    auth = models.CharField(verbose_name="mode de connexion", choices=Auth.choices)
    kind = models.CharField(verbose_name="type d'utilisateur", choices=NexusUserKind.choices, blank=True)

    updated_at = models.DateTimeField(verbose_name="date de modification", auto_now=True, db_index=True)

    include_old = NexusQuerySet.as_manager()
    objects = NexusManager()

    class Meta:
        verbose_name = "utilisateur"
        constraints = [
            models.UniqueConstraint(fields=["email", "source"], name="email_source_unique"),
        ]
        indexes = [models.Index(fields=["source", "updated_at"])]


class NexusStructure(AddressMixin, models.Model):
    id = models.CharField(verbose_name="ID unique", primary_key=True)  # Built from source and source_id

    source = models.CharField(verbose_name="source de la donnée", choices=Service.choices, db_index=True)
    source_id = models.CharField(verbose_name="ID Source")
    source_kind = models.CharField(verbose_name="type d'origine")
    source_link = models.URLField(verbose_name="page du produit sur le service", blank=True)

    siret = models.CharField(verbose_name="siret", max_length=14, db_index=True)
    name = models.CharField(verbose_name="nom")
    kind = models.CharField(verbose_name="type", choices=NexusStructureKind.choices)
    email = CIEmailField("adresse e-mail", db_index=True)
    phone = models.CharField(verbose_name="téléphone", max_length=20, blank=True)
    website = models.URLField(verbose_name="site web", blank=True)
    opening_hours = models.CharField(verbose_name="horaires d'accueil", blank=True)  # FIXME: validate OSM format
    accessibility = models.URLField(
        verbose_name="accessibilité du lieu", blank=True
    )  # FIXME: should always start with https://acceslibre.beta.gouv.fr/, add validator
    description = models.TextField(verbose_name="description", blank=True)

    updated_at = models.DateTimeField(verbose_name="date de modification", auto_now=True, db_index=True)

    include_old = NexusQuerySet.as_manager()
    objects = NexusManager()

    class Meta:
        verbose_name = "structure"
        indexes = [models.Index(fields=["source", "updated_at"])]


class NexusMembership(models.Model):
    source = models.CharField(verbose_name="source de la donnée", choices=Service.choices)
    user = models.ForeignKey(
        NexusUser,
        verbose_name="utilisateur",
        related_name="memberships",
        on_delete=models.CASCADE,
    )
    structure = models.ForeignKey(
        NexusStructure,
        verbose_name="structure",
        related_name="memberships",
        on_delete=models.CASCADE,
    )
    role = models.CharField(verbose_name="rôle", choices=Role.choices)

    updated_at = models.DateTimeField(verbose_name="date de modification", auto_now=True, db_index=True)

    include_old = NexusQuerySet.as_manager()
    objects = NexusManager()

    class Meta:
        verbose_name = "membre"
        constraints = [
            models.UniqueConstraint(fields=["user", "structure"], name="user_structure_unique"),
        ]
        indexes = [models.Index(fields=["source", "updated_at"])]


class APIFullSync(models.Model):
    """
    Stores nexus ressources validity threshold.

    For a given service, all objects with this service as source, and with
    an updated_at value older than APIFullSync.timestamp are ignored.

    This is done with their default manager NexusManager.

    new_start_at is used to temporarly store a new full sync start until it's finished
    and it becomes the new timestamp.
    """

    service = models.CharField(verbose_name="service", choices=Service.choices, unique=True)
    new_start_at = models.DateTimeField(verbose_name="date début de synchronisation", null=True)
    timestamp = models.DateTimeField(verbose_name="date de dernière synchronisation", default=DEFAULT_THRESHOLD)

    class Meta:
        verbose_name = "dernière sychronisation complète de l'API"

    def __str__(self):
        return f"{self.service} - {self.timestamp}"
