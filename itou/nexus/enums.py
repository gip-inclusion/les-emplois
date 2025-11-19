from django.db import models


class Service(models.TextChoices):
    COMMUNAUTE = "la-communauté", "La communauté"
    DORA = "dora", "Dora"
    EMPLOIS = "emplois-de-linclusion", "les emplois"
    MARCHE = "le-marche", "Le marché"
    MON_RECAP = "mon-recap", "Mon Recap"
    PILOTAGE = "pilotage", "Le pilotage"


class Auth(models.TextChoices):
    DJANGO = "DJANGO", "Django"
    MAGIK_LINK = "MAGIK_LINK", "Lien magique"
    INCLUSION_CONNECT = "INCLUSION_CONNECT", "Inclusion Connect"
    PRO_CONNECT = "PRO_CONNECT", "ProConnect"
