from django.db import models


class ApprovalStatus(models.TextChoices):
    EXPIRED = "EXPIRED", "Expiré"
    VALID = "VALID", "Valide"
    FUTURE = "FUTURE", "Valide (non démarré)"
    SUSPENDED = "SUSPENDED", "Valide (suspendu)"


class Origin(models.TextChoices):
    DEFAULT = "default", "Créé normalement via les emplois"
    PE_APPROVAL = "pe_approval", "Créé lors d'un import d'Agrément Pole Emploi"
    AI_STOCK = "ai_stock", "Créé lors de l'import du stock AI"
    ADMIN = "admin", "Créé depuis l'admin"
