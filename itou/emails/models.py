from django.contrib.postgres.fields import ArrayField, CIEmailField
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.utils import timezone


class Email(models.Model):
    to = ArrayField(CIEmailField(), verbose_name="à")
    cc = ArrayField(CIEmailField(), default=list, verbose_name="cc")
    bcc = ArrayField(CIEmailField(), default=list, verbose_name="cci")
    subject = models.TextField(verbose_name="sujet")
    body_text = models.TextField(verbose_name="message")
    from_email = CIEmailField(verbose_name="de")
    reply_to = ArrayField(CIEmailField(), default=list, verbose_name="répondre à")
    created_at = models.DateTimeField(default=timezone.now, db_index=True, verbose_name="demande d’envoi à")
    esp_response = models.JSONField(null=True, verbose_name="réponse du fournisseur d’e-mail")

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            GinIndex(name="recipients_idx", fields=["to", "cc", "bcc"]),
        ]

    def __str__(self):
        return f"email {self.pk}: {self.subject}"
