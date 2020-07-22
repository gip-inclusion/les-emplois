import ast
from django.conf import settings
from django.db import models
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _


class ExternaUserDataQuery(models.QuerySet):
    def for_user(self, user):
        return self.filter(user__pk=user.pk)


class ASTLiteralField(models.CharField):

    def from_db_value(self, value, expression, connection):
        return ast.literal_eval(value)

    def get_prep_value(self, value):
        print(f"to DB: {value}")
        return repr(value) if type(value) == str else str(value)


class ExternalUserData(models.Model):
    """
    User data acquired by **external** sources (mainly APIs like PE)
    When possible, relevant data is updated directly in the User model (address and birth date for instance)
    If external data is not usable "as-is", it is stored as timestamped key/value pair for further processing.
    """

    objects = models.Manager.from_queryset(ExternaUserDataQuery)()

    created_at = models.DateTimeField(verbose_name=_("Date de création de l'import"), default=now)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Candidat / Utilisateur API PE"),
        on_delete=models.CASCADE,
        related_name="external_user_data",
    )

    # Data import status (for possible retry)

    STATUS_OK = "OK"
    STATUS_PARTIAL = "PARTIAL"
    STATUS_FAILED = "FAILED"
    STATUS_CHOICES = (
        (STATUS_OK, _("Import de données réalisé sans erreur")),
        (STATUS_PARTIAL, _("Import de données réalisé partiellement")),
        (STATUS_FAILED, _("Import de données en erreur")),
    )

    status = models.CharField(max_length=10, choices=STATUS_CHOICES)

    # Data sources : external data providers (APIs)
    # Mainly PE at the moment

    DATA_SOURCE_PE_CONNECT = "PE_CONNECT"
    DATA_SOURCE_UNKNOWN = "UNKNOWN"
    DATA_SOURCE_CHOICES = (
        (DATA_SOURCE_PE_CONNECT, _("API PE Connect")),
        (DATA_SOURCE_UNKNOWN, _("Source non repertoriée")),
    )

    source = models.CharField(
        max_length=20, verbose_name=_("Origine des données externes sur l'utilisateur"), choices=DATA_SOURCE_CHOICES, default=DATA_SOURCE_UNKNOWN
    )

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

    KEY_CHOICES = ((KEY_IS_PE_JOBSEEKER, _("L'utilisateur est inscrit comme demandeur d'emploi PE")),
                   (KEY_HAS_MINIMAL_SOCIAL_ALLOWANCE, _("L'utilisateur dispose d'une prestation de minima sociaux")))

    key = models.CharField(max_length=32, verbose_name=_("Clé"), choices=KEY_CHOICES, default=KEY_UNKNOWN)

    value = ASTLiteralField(max_length=512, verbose_name=_("Valeur"), null=True)

    class Meta:
        verbose_name = _("Informations externes complémentaires sur l'utilisateur (API externes)")
        unique_together = ["key", "user"]

    def __str__(self):
        return f"[{self.pk}] ExternalUserData: user={self.user.pk}, created_at={self.created_at}"

    @staticmethod
    def exists_for_user(user):
        return ExternalUserData.objects.for_user(user).exists()
