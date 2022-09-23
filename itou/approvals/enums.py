from django.db import models


class ApprovalStatus(models.TextChoices):
    EXPIRED = "EXPIRED", "Expiré"
    VALID = "VALID", "Valide"
    FUTURE = "FUTURE", "Valide (non démarré)"
    SUSPENDED = "SUSPENDED", "Valide (suspendu)"
