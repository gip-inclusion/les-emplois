from django.db import models


class InvitationType(models.TextChoices):
    SMS = "sms", "SMS"
    EMAIL = "email", "E-mail"
    POSTAL = "postal", "Courrier"


class InvitationStatus(models.TextChoices):
    SENT = "sent", "Envoyée"
    DELIVERED = "delivered", "Délivrée"
    OPENED = "opened", "Ouverte"
