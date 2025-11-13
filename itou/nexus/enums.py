from django.db import models


class Sources(models.TextChoices):
    EMPLOIS = "les-emplois", "les emplois"
    MARCHE = "le-marche", "Le marché"
    COMMUNAUTE = "la-communauté", "La communauté"
    DORA = "dora", "Dora"


class Auth(models.TextChoices):
    DJANGO = "DJANGO", "Django"
    MAGIK_LINK = "MAGIK_LINK", "Lien magique"
    INCLUSION_CONNECT = "INCLUSION_CONNECT", "Inclusion Connect"
    PRO_CONNECT = "PRO_CONNECT", "ProConnect"
