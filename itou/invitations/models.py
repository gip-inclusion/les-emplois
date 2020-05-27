import logging

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.utils.translation import gettext_lazy as _


logger = logging.getLogger(__name__)


class InvitationManager(models.Manager):
    def get_from_encoded_pk(self, encoded_pk):
        pk = int(urlsafe_base64_decode(encoded_pk))
        return self.get(pk=pk)


class Invitation(models.Model):

    email = models.EmailField(verbose_name=_("E-mail"))
    first_name = models.CharField(verbose_name=_("Prénom"), max_length=255)
    last_name = models.CharField(verbose_name=_("Nom"), max_length=255)
    sent = models.BooleanField(verbose_name=_("Envoyée"), default=False)
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Parrain ou marraine"),
        on_delete=models.CASCADE,
        related_name="invitations",
    )
    accepted = models.BooleanField(verbose_name=_("Acceptée"), default=False)
    created_at = models.DateTimeField(verbose_name=_("Date de création"), default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(verbose_name=_("Date de modification"), blank=True, null=True, db_index=True)

    objects = InvitationManager()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.email}"

    def save(self, *args, **kwargs):
        self.updated_at = timezone.now()
        return super().save(*args, **kwargs)

    @property
    def encoded_pk(self):
        return urlsafe_base64_encode(force_bytes(self.pk))

    @property
    def acceptance_link(self):
        return reverse("invitations_views:accept", kwargs={"encoded_invitation_id": self.encoded_pk})
