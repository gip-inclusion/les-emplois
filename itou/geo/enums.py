from django.db import models


class ZRRStatus(models.TextChoices):
    IN_ZRR = "C", "Classée en ZRR"
    NOT_IN_ZRR = "NC", "Non-classée en ZRR"
    PARTIALLY_IN_ZRR = "PC", "Partiellement classée en ZRR"
