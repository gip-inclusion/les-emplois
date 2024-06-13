from citext import CIEmailField
from django.conf import settings
from django.db import models
from django.utils import timezone


class ExternalDataImportQuerySet(models.QuerySet):
    def pe_sources(self):
        return self.filter(source=ExternalDataImport.DATA_SOURCE_PE_CONNECT)


class ExternalDataImport(models.Model):
    """
    Store API calls made when importing external data of a given user.

    Each call to an external source has a timestamp, an execution status, and an origin.

    The goal of each API call is to gather data that may or may not fit directly in the model of the app.

    Each api call is processed and rendered as a list of key/value pairs (see ExternalUserData class).
    """

    # Data sources : external data providers (APIs)
    # Mainly PE at the moment

    DATA_SOURCE_PE_CONNECT = "PE_CONNECT"
    DATA_SOURCE_UNKNOWN = "UNKNOWN"
    DATA_SOURCE_CHOICES = (
        (DATA_SOURCE_PE_CONNECT, "API PE Connect"),
        (DATA_SOURCE_UNKNOWN, "Autre"),
    )

    STATUS_OK = "OK"
    STATUS_PARTIAL = "PARTIAL"
    STATUS_PENDING = "PENDING"
    STATUS_FAILED = "FAILED"
    STATUS_CHOICES = (
        (STATUS_OK, "Import de données réalisé sans erreur"),
        (STATUS_PARTIAL, "Import de données réalisé partiellement"),
        (STATUS_PENDING, "Import de données en cours"),
        (STATUS_FAILED, "Import de données en erreur"),
    )

    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now)
    source = models.CharField(
        max_length=20, verbose_name="origine des données", choices=DATA_SOURCE_CHOICES, default=DATA_SOURCE_UNKNOWN
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="utilisateur", on_delete=models.CASCADE)
    report = models.JSONField(verbose_name="rapport technique", default=dict)

    objects = ExternalDataImportQuerySet.as_manager()

    class Meta:
        verbose_name = "import de données externes"
        verbose_name_plural = "imports de données externes"
        unique_together = ["user", "source"]

    def __repr__(self):
        return f"ExternalDataImport: pk={self.pk}, user-pk={self.user.pk}, status={self.status}, source={self.source}"

    def __str__(self):
        return f"Import {self.source} pour {self.user.email}"


# External user data: the return


class JobSeekerExternalData(models.Model):
    class Meta:
        verbose_name = "données externes pour un chercheur d'emploi"
        verbose_name_plural = "données externes pour un chercheur d'emploi"

    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now)

    data_import = models.ForeignKey(ExternalDataImport, on_delete=models.CASCADE)

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, verbose_name="demandeur d'emploi", on_delete=models.CASCADE, primary_key=True
    )

    # Is the user a job seeker ? (from PE perspective)
    # --
    # original field: PE / codeStatutIndividu
    is_pe_jobseeker = models.BooleanField(
        null=True, verbose_name="l'utilisateur est inscrit comme demandeur d'emploi PE"
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
        null=True, verbose_name="l'utilisateur dispose d'une prestation de minima sociaux"
    )

    def __repr__(self):
        return (
            f"[self.pk] JobSeekerExternalData: user={self.user.pk}, "
            f"created_at={self.created_at}, data_import={self.data_import.pk}"
        )


class RejectedEmailEventData(models.Model):
    class Meta:
        verbose_name = "donnée collectée par le webhook en cas d’erreur d’envoi d’email"
        verbose_name_plural = "données collectées par le webhook en cas d’erreur d’envoi d’email"

    REASON_INVALID = "invalid"
    REASON_BOUNCED = "bounced"
    REASON_TIMED_OUT = "timed_out"
    REASON_BLOCKED = "blocked"
    REASON_SPAM = "spam"
    REASON_UNSUBSCRIBED = "unsubscribed"
    REASON_OTHER = "other"

    REASON_CHOICES = (
        (REASON_INVALID, "Adresse du destinataire invalide"),
        (REASON_BOUNCED, "Adresse préalablement 'bounced' par notre ESP"),
        (REASON_TIMED_OUT, "Trop de tentatives d’envoi en erreur sur ce destinataire"),
        (REASON_BLOCKED, "La politique de notre ESP interdit ce destinataire"),
        (REASON_SPAM, "Le destinataire nous a taggué comme spammeurs"),
        (REASON_UNSUBSCRIBED, "Le destinataire ne souhaite plus recevoir ces emails"),
        (REASON_OTHER, "Non précisé par l’ESP"),
    )

    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now)
    recipient = CIEmailField("adresse e-mail du destinataire", blank=True, db_index=True)
    reason = models.CharField("la raison du refus de l’envoi d’email", max_length=12, choices=REASON_CHOICES)
