"""
Enums fields used in User models.
"""

from django.db import models


class Title(models.TextChoices):
    M = "M", "Monsieur"
    MME = "MME", "Madame"


class IdentityProvider(models.TextChoices):
    FRANCE_CONNECT = "FC", "FranceConnect"
