from django.db import models


class Service(models.TextChoices):
    COMMUNAUTE = "la-communaute", "La communauté de l’inclusion"
    DATA_INCLUSION = "data-inclusion", "Data inclusion"
    DORA = "dora", "Dora"
    EMPLOIS = "les-emplois", "les emplois de l’inclusion"
    MARCHE = "le-marche", "Le marché de l’inclusion"
    MON_RECAP = "mon-recap", "Mon Récap"
    PILOTAGE = "pilotage", "Le pilotage de l’inclusion"
