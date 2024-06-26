import secrets

from django.db import models
from django.utils import timezone

from itou.companies.models import Company


def _generate_key():
    return secrets.token_urlsafe()


class CompanyToken(models.Model):
    key = models.CharField(default=_generate_key, unique=True, editable=False)
    label = models.CharField(verbose_name="mémo permettant d'identifier l'usage du jeton", max_length=60, unique=True)
    created_at = models.DateTimeField(default=timezone.now)
    companies = models.ManyToManyField(Company, related_name="api_tokens")

    class Meta:
        verbose_name = "jeton d'API entreprise"
        verbose_name_plural = "jetons d'API entreprise"
