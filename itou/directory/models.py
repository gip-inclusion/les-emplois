from django.conf import settings
from django.db import models

from itou.directory.enums import ContactSubject
from itou.users.enums import UserKind


class DirectoryProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name="utilisateur",
        on_delete=models.CASCADE,
        related_name="directory_profile",
        limit_choices_to={"kind": UserKind.PROFESSIONAL},
    )
    is_opted_out = models.BooleanField(
        verbose_name="ne pas apparaître dans l'annuaire des professionnels",
        default=False,
    )

    class Meta:
        verbose_name = "profil de l'annuaire"
        verbose_name_plural = "profils de l'annuaire"

    def __str__(self):
        return f"Profil annuaire de {self.user}"


class ContactMessage(models.Model):
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="expéditeur",
        on_delete=models.CASCADE,
        related_name="+",
    )
    recipient_id = models.CharField(verbose_name="identifiant du destinataire")
    subject = models.CharField(verbose_name="objet", choices=ContactSubject.choices)
    custom_subject = models.CharField(verbose_name="objet personnalisé", blank=True)
    created_at = models.DateTimeField(verbose_name="date d'envoi", auto_now_add=True)

    class Meta:
        verbose_name = "message envoyé via l'annuaire"
        verbose_name_plural = "messages envoyés via l'annuaire"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Message de {self.sender} à {self.recipient_id}"
