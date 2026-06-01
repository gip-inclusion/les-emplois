from django.db import models


class ProfileFlag(models.TextChoices):
    """Booléens calculés à partir des modèles existants (ou hardcodés en v1)."""

    RSA = "rsa", "RSA"
    DELD = "deld", "DELD"
    DETLD = "detld", "DETLD"
    JEUNE = "jeune", "Jeune"
    SENIOR = "senior", "Senior"
    QPV = "qpv", "QPV"
    ZRR = "zrr", "ZRR"
    OETH = "oeth", "OETH"
