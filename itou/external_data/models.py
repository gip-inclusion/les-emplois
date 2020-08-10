import ast

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _


class ExternalDataImportQuerySet(models.QuerySet):
    def for_user(self, user):
        return self.filter(user__pk=user.pk)

    def pe_import_for_user(self, user):
        return self.for_user(user).filter(source=ExternalDataImport.DATA_SOURCE_PE_CONNECT)


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
    created_at = models.DateTimeField(verbose_name=_("Date de création"), default=now)

    # Data sources : external data providers (APIs)
    # Mainly PE at the moment

    DATA_SOURCE_PE_CONNECT = "PE_CONNECT"
    DATA_SOURCE_UNKNOWN = "UNKNOWN"
    DATA_SOURCE_CHOICES = (
        (DATA_SOURCE_PE_CONNECT, _("API PE Connect")),
        (DATA_SOURCE_UNKNOWN, _("Source non repertoriée")),
    )

    source = models.CharField(
        max_length=20, verbose_name=_("Origine des données"), choices=DATA_SOURCE_CHOICES, default=DATA_SOURCE_UNKNOWN
    )

    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name=_("Utilisateur"), on_delete=models.CASCADE)

    report = models.JSONField(verbose_name=_("Rapport technique"), default=dict)

    class Meta:
        verbose_name = _("Import de données externes")
        verbose_name_plural = _("Imports de données externes")
        unique_together = ["user", "source"]

    def __repr__(self):
        return f"ExternalDataImport: pk={self.pk}, user-pk={self.user.pk}, status={self.status}, source={self.source}"

    def __str__(self):
        return f"Import {self.source} pour {self.user.email}"


# External user data: the return


class JobSeekerExternalData(models.Model):
    class Meta:
        verbose_name = _("Données externes pour un chercheur d'emploi")
        verbose_name_plural = _("Données externes pour un chercheur d'emploi")

    created_at = models.DateTimeField(default=now, verbose_name=_("Date de création"))

    data_import = models.ForeignKey(ExternalDataImport, on_delete=models.CASCADE)

    user = models.OneToOneField(get_user_model(), on_delete=models.CASCADE, primary_key=True)

    # Is the user a job seeker ? (from PE perspective)
    # --
    # original field: PE / codeStatutIndividu
    is_pe_jobseeker = models.BooleanField(
        null=True, verbose_name=_("L'utilisateur est inscrit comme demandeur d'emploi PE")
    )

    # The user has open rights to **at least one** the following social helps;
    # * ASS (Allocation Solidarité Spécifique)
    # * AAH (Allocation Adulte Handicapé)
    # * RSA (Revenue Solidarité Active)
    # * AER (Allocation Equivalent Retraite)
    #
    # These are 1st level eligibility criterias, except for AER
    # --
    # original field: PE / beneficiairePrestationSolidarite
    has_minimal_social_allowance = models.BooleanField(
        null=True, verbose_name=_("L'utilisateur dispose d'une prestation de minima sociaux")
    )

    def __repr__(self):
        return f"[self.pk] JobSeekerExternalData: user={self.user.pk}, created_at={self.created_at}, data_import={self.data_import.pk}"
