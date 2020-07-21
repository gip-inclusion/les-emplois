from django.conf import settings
from django.db import models
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _


class ExternaUserDataQuery(models.QuerySet):
    def for_user(self, user):
        return self.filter(user__pk=user.pk)


class ExternalUserData(models.Model):
    """
    User data acquired by **external** sources (mainly APIs like PE)
    When possible, relevant data is updated directly in the User model (address and birth date for instance)
    If external data is not usable "as-is", it is stored here for further processing.
    """
    objects = models.Manager.from_queryset(ExternaUserDataQuery)()

    created_at = models.DateTimeField(verbose_name=_("Date de création de l'import"), default=now)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Candidat / Utilisateur API PE"),
        on_delete=models.CASCADE,
        related_name="external_user_data",
    )

    STATUS_OK = "OK"
    STATUS_PARTIAL = "PARTIAL"
    STATUS_FAILED = "FAILED"
    STATUS_CHOICES = (
        (STATUS_OK, _("Import de données réalisé sans erreur")),
        (STATUS_PARTIAL, _("Import de données réalisé partiellement")),
        (STATUS_FAILED, _("Import de données en erreur")),
    )

    status = models.CharField(max_length=10, choices=STATUS_CHOICES)

    # The user has open rights to **at least one** the following social helps;
    # * ASS (! Allocation Solidarité Spécifique)
    # * AAH (Allocation Adulte Handicapé)
    # * RSA (Revenue Solidarité Active)
    # * AER (Allocation Equivalent Retraite)
    #
    # These are 1st level eligibility criterias, except for AER
    #
    # original field: PE / beneficiairePrestationSolidarite
    has_social_allowance = models.BooleanField(verbose_name=_("L'utilisateur est béneficiaire d'un ou plusieurs minima sociaux"))

    # Is the user a job seeker ? (from PE perspective)
    #
    # original field: PE / codeStatutIndividu
    is_pe_jobseeker = models.BooleanField(verbose_name=_("L'utilisateur est demandeur d'emploi (PE)"))

    class Meta:
        verbose_name = _("Informations externes complémentaires sur l'utilisateur (API externes)")

    def __str__(self):
        return f"[{self.pk}] ExternalUserData: user={self.user.pk}, created_at={self.created_at}"

    @staticmethod
    def exists_for_user(user):
        return ExternalUserData.objects.for_user(user).exists()
