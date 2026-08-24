from django.db import models

from itou.companies import enums as companies_enums


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
        "Difficultés particulièrement importantes dont l'absence de prise en charge ferait "
        "obstacle à son insertion professionnelle",
    )
    # Since December 1, 2021, health context reason can no longer be used
    HEALTH_CONTEXT = "HEALTH_CONTEXT", "Contexte sanitaire"

    @classmethod
    def for_company(cls, company):
        enums = [
            cls.SENIOR_CDI,
            cls.COMPLETE_TRAINING,
            cls.RQTH,
            cls.SENIOR,
        ]
        if company.kind in [companies_enums.CompanyKind.AI, companies_enums.CompanyKind.ACI]:
            enums.append(cls.PARTICULAR_DIFFICULTIES)

        empty = [(None, cls.__empty__)] if hasattr(cls, "__empty__") else []
        return empty + [(enum.value, enum.label) for enum in enums]


class ProlongationBlocker(models.TextChoices):
    """Why a PASS IAE cannot be prolonged.

    Only `DEADLINE_PASSED` can be waived, by a derogation link issued by the support.
    """

    SUSPENDED = "SUSPENDED", "Ce PASS IAE est suspendu, il ne peut pas être prolongé."
    PENDING_REQUEST = (
        "PENDING_REQUEST",
        "Une demande de prolongation est déjà en attente pour ce PASS IAE.",
    )
    NOT_LATEST_APPROVAL = (
        "NOT_LATEST_APPROVAL",
        "Ce PASS IAE n’est pas le PASS IAE le plus récent du candidat, il ne peut donc pas être prolongé.",
    )
    TOO_EARLY = (
        "TOO_EARLY",
        "Ce PASS IAE se termine dans plus de 12 mois, il est trop tôt pour le prolonger.",
    )
    DEADLINE_PASSED = (
        "DEADLINE_PASSED",
        "Ce PASS IAE est arrivé à échéance il y a plus de 6 mois, le délai de prolongation est dépassé.",
    )


class ProlongationRequestStatus(models.TextChoices):
    PENDING = "PENDING", "À traiter"
    GRANTED = "GRANTED", "Acceptée"
    DENIED = "DENIED", "Refusée"


class ProlongationRequestDenyReason(models.TextChoices):
    IAE = "IAE", "L’IAE ne correspond plus aux besoins / à la situation de la personne."
    SIAE = "SIAE", "La typologie de SIAE ne correspond plus aux besoins / à la situation de la personne."
    DURATION = "DURATION", "La durée de prolongation demandée n’est pas adaptée à la situation du candidat."
    REASON = "REASON", "Le motif de prolongation demandé n’est pas adapté à la situation du candidat."


class ProlongationRequestDenyProposedAction(models.TextChoices):
    # TODO: Clarify the actions to improve the naming
    EXIT_IAE = (
        "EXIT_IAE",
        "Accompagnement à la recherche d’emploi hors IAE et mobilisation de l’offre "
        "de services disponible au sein de votre structure ou celle d’un partenaire.",
    )
    SOCIAL_PARTNER = "SOCIAL_PARTNER", "Orientation vers un partenaire de l’accompagnement social/professionnel."
    OTHER = "OTHER", "Autre"
