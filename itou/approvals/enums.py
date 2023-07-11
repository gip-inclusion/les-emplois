from django.db import models

from itou.siaes import enums as siaes_enums


class ApprovalStatus(models.TextChoices):
    EXPIRED = "EXPIRED", "Expiré"
    VALID = "VALID", "Valide"
    FUTURE = "FUTURE", "Valide (non démarré)"
    SUSPENDED = "SUSPENDED", "Valide (suspendu)"


class Origin(models.TextChoices):
    DEFAULT = "default", "Créé normalement via les emplois"
    PE_APPROVAL = "pe_approval", "Créé lors d'un import d'Agrément Pole Emploi"
    # On November 30th, 2021, AI were delivered approvals without a diagnosis.
    AI_STOCK = "ai_stock", "Créé lors de l'import du stock AI"
    ADMIN = "admin", "Créé depuis l'admin"


class ProlongationReason(models.TextChoices):
    SENIOR_CDI = "SENIOR_CDI", "CDI conclu avec une personne de plus de 57 ans"
    COMPLETE_TRAINING = "COMPLETE_TRAINING", "Fin d'une formation"
    RQTH = "RQTH", "RQTH - Reconnaissance de la qualité de travailleur handicapé"
    SENIOR = "SENIOR", "50 ans et plus"
    # Exclusive to AI and ACI
    PARTICULAR_DIFFICULTIES = (
        "PARTICULAR_DIFFICULTIES",
        "Difficultés particulières qui font obstacle à l'insertion durable dans l’emploi",
    )
    # Since December 1, 2021, health context reason can no longer be used
    HEALTH_CONTEXT = "HEALTH_CONTEXT", "Contexte sanitaire"

    @classmethod
    def for_siae(cls, siae):
        enums = [
            cls.SENIOR_CDI,
            cls.COMPLETE_TRAINING,
            cls.RQTH,
            cls.SENIOR,
        ]
        if siae.kind in [siaes_enums.SiaeKind.AI, siaes_enums.SiaeKind.ACI]:
            enums.append(cls.PARTICULAR_DIFFICULTIES)

        empty = [(None, cls.__empty__)] if hasattr(cls, "__empty__") else []
        return empty + [(enum.value, enum.label) for enum in enums]
