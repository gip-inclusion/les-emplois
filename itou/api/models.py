import uuid

from django.db import models
from django.utils import timezone

from itou.companies.models import Siae


class SiaeApiToken(models.Model):
    key = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    label = models.CharField(verbose_name="mémo permettant d'identifier l'usage du jeton", max_length=60, unique=True)
    created_at = models.DateTimeField(default=timezone.now)
    siaes = models.ManyToManyField(Siae, related_name="api_tokens")

    class Meta:
        verbose_name = "jeton d'API SIAE"
        verbose_name_plural = "jetons d'API SIAE"
