from django.db import models


class Service(models.TextChoices):
    COMMUNAUTE = "la-communauté", "La communauté"
    DATA_INCLUSION = "data-inclusion", "Data inclusion"
    DORA = "dora", "Dora"
    EMPLOIS = "les-emplois", "les emplois"
    MARCHE = "le-marche", "Le marché"
    MON_RECAP = "mon-recap", "Mon Recap"
    PILOTAGE = "pilotage", "Le pilotage"
