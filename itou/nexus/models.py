import uuid

from citext import CIEmailField
from django.db import models

from itou.common_apps.address.models import AddressMixin
from itou.nexus.enums import Auth, Service


class User(models.Model):
    id = models.CharField(verbose_name="ID unique", primary_key=True)  # Built from source and source_id

    source = models.CharField(verbose_name="source de la donnée", choices=Service.choices)
    source_id = models.CharField(verbose_name="ID Source")

    first_name = models.CharField(verbose_name="prénom")
    last_name = models.CharField(verbose_name="nom")
    email = CIEmailField("adresse e-mail", db_index=True)
    phone = models.CharField(verbose_name="téléphone", max_length=20, blank=True)
    last_login = models.DateTimeField(verbose_name="date de denière connexion")
    auth = models.CharField(verbose_name="mode de connexion", choices=Auth.choices)
    kind = models.CharField(verbose_name="Type d'utilisateur")

    updated_at = models.DateTimeField(verbose_name="date de modification")

    class Meta:
        verbose_name = "utilisateur"
        constraints = [
            models.UniqueConstraint(fields=["email", "source"], name="email_source_unique"),
        ]


class Structure(AddressMixin, models.Model):
    id = models.CharField(verbose_name="ID unique", primary_key=True)  # Built from source and source_id

    source = models.CharField(verbose_name="source de la donnée", choices=Service.choices)
    source_id = models.CharField(verbose_name="ID Source")

    siret = models.CharField(verbose_name="siret", max_length=14, db_index=True)
    name = models.CharField(verbose_name="nom")
    kind = models.CharField(verbose_name="type")
    email = CIEmailField("adresse e-mail", db_index=True)
    phone = models.CharField(verbose_name="téléphone", max_length=20, blank=True)

    updated_at = models.DateTimeField(verbose_name="date de modification")

    class Meta:
        verbose_name = "structure"


class Membership(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)

    source = models.CharField(verbose_name="source de la donnée", choices=Service.choices)
    user = models.ForeignKey(
        User,
        verbose_name="utilisateur",
        on_delete=models.RESTRICT,
    )
    structure = models.ForeignKey(
        Structure,
        verbose_name="structure",
        on_delete=models.RESTRICT,
    )

    class Meta:
        verbose_name = "membre"
