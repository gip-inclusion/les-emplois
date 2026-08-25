import enum

from django.db import models


class ResetRequestState(models.TextChoices):
    PENDING = "pending", "En attente de traitement"
    ACCEPTED = "accepted", "Acceptée (les appareils d’authentification ne sont pas encore supprimés)"
    DENIED = "denied", "Refusée"
    DONE = "done", "Effectuée (les appareils d’authentification ont été supprimés)"


class ResetRequestTransition(enum.StrEnum):
    ACCEPT = "accept"
    RESEND = "resend"
    DENY = "deny"
    RESET_DEVICES = "reset_devices"
