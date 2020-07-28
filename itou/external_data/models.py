import ast

from django.conf import settings
from django.db import models
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _


class ExternalDataImportQuerySet(models.QuerySet):
    def for_user(self, user):
        return self.filter(user__pk=user.pk)

    def last_pe_import_for_user(self, user):
        return self.for_user(user).filter(source=ExternalDataImport.DATA_SOURCE_PE_CONNECT).first()


class ExternalUserDataQuerySet(models.QuerySet):
    def for_user(self, user):
        return self.filter(data_import__user=user)


class ASTLiteralField(models.CharField):
    """
    Custom value field type based on CharField
    Useful for auto-typing key/value for ExternalUserData objects
    """

    def from_db_value(self, value, expression, connection):
        # Process applied when getting value from DB
        return ast.literal_eval(value)

    def get_prep_value(self, value):
        # Process applied when storing value to DB
        return repr(value)


class ExternalDataImport(models.Model):
    """
    Store API calls made when importing external data of a given user.

    Each call to an external source has a timestamp, an execution status, and an origin.

    The goal of each API call is to gather data that may or may not fit directly in the model of the app.

    Each api call is processed and rendered as a list of key/value pairs (see ExternalUserData class).
    """

    objects = models.Manager.from_queryset(ExternalDataImportQuerySet)()

    STATUS_OK = "OK"
    STATUS_PARTIAL = "PARTIAL"
    STATUS_PENDING = "PENDING"
    STATUS_FAILED = "FAILED"
    STATUS_CHOICES = (
        (STATUS_OK, _("Import de données réalisé sans erreur")),
        (STATUS_PARTIAL, _("Import de données réalisé partiellement")),
        (STATUS_PENDING, _("Import de données en cours")),
        (STATUS_FAILED, _("Import de données en erreur")),
    )

    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    created_at = models.DateTimeField(verbose_name=_("Date de création de l'import"), default=now)

    # Data sources : external data providers (APIs)
    # Mainly PE at the moment

    DATA_SOURCE_PE_CONNECT = "PE_CONNECT"
    DATA_SOURCE_UNKNOWN = "UNKNOWN"
    DATA_SOURCE_CHOICES = (
        (DATA_SOURCE_PE_CONNECT, _("API PE Connect")),
        (DATA_SOURCE_UNKNOWN, _("Source non repertoriée")),
    )

    source = models.CharField(
        max_length=20,
        verbose_name=_("Origine des données externes de l'utilisateur"),
        choices=DATA_SOURCE_CHOICES,
        default=DATA_SOURCE_UNKNOWN,
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name=_("Candidat / Utilisateur API PE"), on_delete=models.CASCADE
    )

    class Meta:
        verbose_name = _("Jeu de données externe importé")
        unique_together = ["user", "source"]


class ExternalUserData(models.Model):
    """
    User data acquired by **external** sources (mainly APIs like PE).

    External user data are stored as simple key / value pairs, attached to a parent ExternalDataImport object.

    Documentation about valid keys is included in the code (as Django 'choices'),
    and usable via the 'description' property.

    When possible, relevant data is updated directly in the User model (user address and birthdate for instance).
    If external data is not usable "as-is" or not directly manageable in the app, it is stored as timestamped
    key/value pair for further processing or usage.

    Storing external data as k/v pairs is a way to keep in mind that we do not have "authority" on:
        - value (may change on API provider side),
        - correctness (external data validation is not our responsibility),
        - lifecycle (data may be outdated or updated on the "other side").

    User data could have been stored "flat" with a Django JSONField or Postgres HStore, but:
        - we could lose some useful metadata (like description),
        - documentation on keys / JSON schema is not available directly (keys are documented in the model code).

    Moreover, JSONField and HStore are Postgres specific.
    """

    # Simple key value storage for external data
    #
    # Though "flat is better than nested", each data chunkk needs a source and an import date
    # Model may change to M-N relationship if the number of keys grows to much
    # Add new keys as needed...

    KEY_UNKNOWN = "unknown"

    # Is the user a job seeker ? (from PE perspective)
    # --
    # original field: PE / codeStatutIndividu
    KEY_IS_PE_JOBSEEKER = "is_pe_jobseeker"

    # The user has open rights to **at least one** the following social helps;
    # * ASS (Allocation Solidarité Spécifique)
    # * AAH (Allocation Adulte Handicapé)
    # * RSA (Revenue Solidarité Active)
    # * AER (Allocation Equivalent Retraite)
    #
    # These are 1st level eligibility criterias, except for AER
    # --
    # original field: PE / beneficiairePrestationSolidarite
    KEY_HAS_MINIMAL_SOCIAL_ALLOWANCE = "has_minimal_social_allowance"

    KEY_CHOICES = (
        (KEY_UNKNOWN, _("Clé inconnue")),
        (KEY_IS_PE_JOBSEEKER, _("L'utilisateur est inscrit comme demandeur d'emploi PE")),
        (KEY_HAS_MINIMAL_SOCIAL_ALLOWANCE, _("L'utilisateur dispose d'une prestation de minima sociaux")),
    )

    objects = models.Manager.from_queryset(ExternalUserDataQuerySet)()

    key = models.CharField(max_length=32, verbose_name=_("Clé"), choices=KEY_CHOICES, default=KEY_UNKNOWN)

    created_at = models.DateTimeField(verbose_name=_("Date d'enregistrement des données"), default=now)

    data_import = models.ForeignKey(ExternalDataImport, on_delete=models.CASCADE)

    value = ASTLiteralField(max_length=512, verbose_name=_("Valeur"), null=True)

    class Meta:
        verbose_name = _("Informations complémentaires sur l'utilisateur (API externes)")

    def __repr__(self):
        return f"[{self.pk}] ExternalUserData: key={self.key}, value={self.value}, created_at={self.created_at}"

    def __str__(self):
        return f"{self.key}: {self.value}"

    @property
    def description(self):
        """
        Get a human readable description of the key / value pair (stored in KEY_CHOICES)
        """
        return self.get_key_display()

    class _DictWithAttrs(dict):
        """
        Helper class: add property-like access to a dict
        i.e. accessing user data with `my_ext_data.has_minimal_allowance`

        There may be a better way to do that...
        """

        __getattr__ = dict.get

    @staticmethod
    def user_data_to_dict(user):
        """
        Fetch last set of data imported for user and wrap them in a "custom" dict (with properties access)
        """
        return ExternalUserData._DictWithAttrs(
            {user.key: user.value for user in ExternalUserData.objects.for_user(user)}
        )
