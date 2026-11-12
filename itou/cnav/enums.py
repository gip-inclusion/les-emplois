from django.db import models


class CNAVRecordOrigin(models.TextChoices):
    USER_CREATION = "USER_CREATION", "Création d’un nouvel usager"
