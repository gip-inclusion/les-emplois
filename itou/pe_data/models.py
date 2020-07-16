from django.conf import settings
from django.db import models
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _


class ExtraUserData(models.Model):

    created_at = models.DateTimeField(verbose_name=_("Date de création de l'import"), default=now)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Candidat / Utilisateur API PE"),
        on_delete=models.CASCADE,
        related_name="extrauserdata",
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

    class Meta:
        verbose_name = _("Informations supplémentaires PE Connect")

    def __str__(self):
        return f"[{self.pk}] ExtraUserData: user={self.user.pk}, created_at={self.created_at}"
