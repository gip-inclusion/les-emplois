import datetime

from citext import CIEmailField
from django.db import models
from django.db.models import F, OuterRef
from django.db.models.functions import Coalesce
from django.utils import timezone

from itou.common_apps.address.models import AddressMixin
from itou.nexus.enums import Auth, NexusStructureKind, NexusUserKind, Role, Service
from itou.users.models import User
from itou.utils.validators import validate_siret


# Set a default threshold so that we don't have to handle empty threshold for services without a full sync
DEFAULT_VALID_SINCE = datetime.datetime(2025, 12, 1, tzinfo=datetime.UTC)


class NexusQuerySet(models.QuerySet):
    def with_threshold(self):
        return self.annotate(
            _threshold=Coalesce(
                NexusRessourceSyncStatus.objects.filter(service=OuterRef("source")).values("valid_since")[:1],
                DEFAULT_VALID_SINCE,
            )
        )


class NexusModelMixin:
    @property
    def threshold(self):
        if threshold := getattr(self, "_threshold", None):
            return threshold
        if ressource_sync_status := NexusRessourceSyncStatus.objects.filter(service=self.source).first():
            setattr(self, "_threshold", ressource_sync_status.timestamp)
            return self._threshold
        return DEFAULT_VALID_SINCE


class NexusManager(models.Manager.from_queryset(NexusQuerySet)):
    def get_queryset(self):
        return super().get_queryset().with_threshold().filter(updated_at__gte=F("_threshold"))


class NexusUser(NexusModelMixin, models.Model):
    id = models.CharField(verbose_name="ID unique", primary_key=True)  # Built from source and source_id

    source = models.CharField(verbose_name="source de la donnée", choices=Service.choices)
    source_id = models.CharField(verbose_name="ID source")
    source_kind = models.CharField(verbose_name="type d'origine")

    first_name = models.CharField(verbose_name="prénom")
    last_name = models.CharField(verbose_name="nom")
    # We use the Email to fetch a user activaed services : use an index to speed up the requests
    email = CIEmailField("adresse e-mail", db_index=True)
    phone = models.CharField(verbose_name="téléphone", max_length=20, blank=True)
    last_login = models.DateTimeField(verbose_name="date de denière connexion", null=True)
    auth = models.CharField(verbose_name="mode de connexion", choices=Auth.choices)
    kind = models.CharField(verbose_name="type d'utilisateur", choices=NexusUserKind.choices, blank=True)

    updated_at = models.DateTimeField(verbose_name="date de modification", auto_now=True)

    include_old = NexusQuerySet.as_manager()
    objects = NexusManager()

    class Meta:
        verbose_name = "utilisateur"
        constraints = [
            models.UniqueConstraint(fields=["email", "source"], name="email_source_unique"),
        ]


class NexusStructure(NexusModelMixin, AddressMixin, models.Model):
    # Built from source and source_id, matches the id in data-inclusion database
    id = models.CharField(verbose_name="ID unique", primary_key=True)
    source = models.CharField(verbose_name="source de la donnée", choices=Service.choices)
    source_id = models.CharField(verbose_name="ID Source")
    source_kind = models.CharField(verbose_name="type d'origine", blank=True)
    source_link = models.URLField(verbose_name="page du produit sur le service", blank=True)

    siret = models.CharField(
        verbose_name="siret",
        max_length=14,
        validators=[validate_siret],
        db_index=True,
        null=True,  # Some FT structures don't have sirets
    )
    name = models.CharField(verbose_name="nom")
    kind = models.CharField(verbose_name="type", choices=NexusStructureKind.choices, blank=True)
    email = CIEmailField("adresse e-mail")
    phone = models.CharField(verbose_name="téléphone", max_length=20, blank=True)
    website = models.URLField(verbose_name="site web", blank=True)
    opening_hours = models.CharField(verbose_name="horaires d'accueil", blank=True)  # TODO: validate OSM format
    accessibility = models.URLField(
        verbose_name="accessibilité du lieu", blank=True
    )  # TODO: should always start with https://acceslibre.beta.gouv.fr/, add validator
    description = models.TextField(verbose_name="description", blank=True)

    updated_at = models.DateTimeField(verbose_name="date de modification", auto_now=True)

    include_old = NexusQuerySet.as_manager()
    objects = NexusManager()

    class Meta:
        verbose_name = "structure"


class NexusMembership(NexusModelMixin, models.Model):
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
    source = models.CharField(verbose_name="source de la donnée", choices=Service.choices)
    role = models.CharField(verbose_name="rôle", choices=Role.choices)

    updated_at = models.DateTimeField(verbose_name="date de modification", auto_now=True)

    include_old = NexusQuerySet.as_manager()
    objects = NexusManager()

    class Meta:
        verbose_name = "membre"
        constraints = [
            models.UniqueConstraint(fields=["user", "structure"], name="user_structure_unique"),
        ]


class NexusRessourceSyncStatus(models.Model):
    """
    Stores nexus ressources validity threshold.

    For a given service, all objects with this service as source, and with
    an updated_at value older than NexusRessourceSyncStatus.valid_since are ignored.

    This is done with their default manager NexusManager.

    in_progress_since is used to temporarly store a new full sync start until it's finished
    and it becomes the new valid_since.
    """

    service = models.CharField(verbose_name="service", choices=Service.choices, unique=True)
    in_progress_since = models.DateTimeField(verbose_name="date début de synchronisation", null=True)
    valid_since = models.DateTimeField(verbose_name="date de dernière synchronisation", default=DEFAULT_VALID_SINCE)

    class Meta:
        verbose_name = "statut de synchronisation"

    def __str__(self):
        return f"{self.service} - {self.valid_since}"


class ActivatedService(models.Model):
    user = models.ForeignKey(
        User,
        verbose_name="utilisateur",
        related_name="activated_services",
        on_delete=models.CASCADE,
    )
    service = models.CharField(verbose_name="service", choices=Service.choices)
    created_at = models.DateTimeField(verbose_name="date d'activation", default=timezone.now)

    class Meta:
        verbose_name = "service activé"
        verbose_name_plural = "services activés"
