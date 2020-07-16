from django.db import models
from django.utils.translation import gettext_lazy as _
from django.conf import settings

class ExtraUserData(models.Model):

    created_at = models.DateTimeField(verbose_name=_("Date de création de l'import"))
    user = models.ForeignKey(settings.AUTH_USER_MODEL, 
                             verbose_name=_("Candidat / Utilisateur API PE"), 
                             on_delete=models.CASCADE,
                             related_name="extrauserdata")

    STATUS_CHOICES = (("OK", _("Import de données réalisé sans erreur")),
                      ("PARTIAL", _("Import de données réalisé partiellement")),
                      ("FAILED", _("Import de données en erreur")))

    status = models.CharField(max_length=10, choices=STATUS_CHOICES)

    class Meta:
        verbose_name = _("Informations supplémentaires PE Connect")

    def __str__(self):
        return f"[{self.pk}] ExtraUserData: user={self.user.pk}, created_at={self.created_at}"
