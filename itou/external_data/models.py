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
    Track of API calls made for importing given user external data
    """

    objects = models.Manager.from_queryset(ExternalDataImportQuerySet)()

    STATUS_OK = "OK"
    STATUS_PARTIAL = "PARTIAL"
    STATUS_PROCESSING = "PROCESSING"
    STATUS_FAILED = "FAILED"
    STATUS_CHOICES = (
        (STATUS_OK, _("Import de données réalisé sans erreur")),
        (STATUS_PARTIAL, _("Import de données réalisé partiellement")),
        (STATUS_PROCESSING, _("Import de données réalisé en cours")),
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
        verbose_name=_("Origine des données externes sur l'utilisateur"),
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
    User data acquired by **external** sources (mainly APIs like PE)
    When possible, relevant data is updated directly in the User model (address and birth date for instance)
    If external data is not usable "as-is", it is stored as timestamped key/value pair for further processing.
    """

    objects = models.Manager.from_queryset(ExternalUserDataQuerySet)()

    created_at = models.DateTimeField(verbose_name=_("Date d'enregistrement des données"), default=now)

    data_import = models.ForeignKey(ExternalDataImport, on_delete=models.CASCADE)

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
    # * ASS (! Allocation Solidarité Spécifique)
    # * AAH (Allocation Adulte Handicapé)
    # * RSA (Revenue Solidarité Active)
    # * AER (Allocation Equivalent Retraite)
    #
    # These are 1st level eligibility criterias, except for AER
    # --
    # original field: PE / beneficiairePrestationSolidarite
    KEY_HAS_MINIMAL_SOCIAL_ALLOWANCE = "has_minimal_social_allowance"

    KEY_CHOICES = (
        (KEY_IS_PE_JOBSEEKER, _("L'utilisateur est inscrit comme demandeur d'emploi PE")),
        (KEY_HAS_MINIMAL_SOCIAL_ALLOWANCE, _("L'utilisateur dispose d'une prestation de minima sociaux")),
    )

    key = models.CharField(max_length=32, verbose_name=_("Clé"), choices=KEY_CHOICES, default=KEY_UNKNOWN)

    value = ASTLiteralField(max_length=512, verbose_name=_("Valeur"), null=True)

    class Meta:
        verbose_name = _("Informations externes complémentaires sur l'utilisateur (API externes)")

    def __repr__(self):
        return f"[{self.pk}] ExternalUserData: created_at={self.created_at}"

    def __str__(self):
        return f"{self.key}: {self.value}"

    def description(self):
        return self.get_key_display()

    class _AttrDict(dict):
        __getattr__ = dict.get

    @staticmethod
    def last_data_to_dict(user):
        """
        Fetch last set of data imported for user and wrap them in a dict
        """
        return ExternalUserData._AttrDict({user.key: user.value for user in ExternalUserData.objects.for_user(user)})
