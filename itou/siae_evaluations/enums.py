from django.db import models

from itou.companies.enums import SiaeKind


class EvaluationChosenPercent:
    MIN = 20
    DEFAULT = 30
    MAX = 40


class EvaluationSiaesKind:
    Evaluable = [SiaeKind.AI, SiaeKind.EI, SiaeKind.ACI, SiaeKind.ETTI]


class EvaluationJobApplicationsBoundariesNumber:
    SELECTION_PERCENTAGE = 20

    # one SIAE can be selected in evaluation if it made
    # at least MIN job applications with self-approval
    # during the evaluated period
    MIN = 2

    # whenever one SIAE made more than MAX job applications with self-approval
    # during the evaluated period, only MAX job applications maximum will be
    # added into the evaluation campaign
    MAX = 20


class EvaluatedJobApplicationsState(models.TextChoices):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    UPLOADED = "UPLOADED"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REFUSED = "REFUSED"
    REFUSED_2 = "REFUSED_2"


class EvaluatedJobApplicationsSelectCriteriaState(models.TextChoices):
    PENDING = "PENDING"
    EDITABLE = "EDITABLE"
    NOTEDITABLE = "NOTEDITABLE"


class EvaluatedSiaeState(models.TextChoices):
    PENDING = "PENDING"
    SUBMITTABLE = "SUBMITTABLE"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REFUSED = "REFUSED"
    ADVERSARIAL_STAGE = "ADVERSARIAL_STAGE"


class EvaluatedSiaeNotificationReason(models.TextChoices):
    DELAY = ("DELAY", "Non respect des délais")
    INVALID_PROOF = ("INVALID_PROOF", "Pièce justificative incorrecte")
    MISSING_PROOF = ("MISSING_PROOF", "Pièce justificative manquante")
    OTHER = ("OTHER", "Autre")


class EvaluatedAdministrativeCriteriaState(models.TextChoices):
    PENDING = ("PENDING", "En attente")
    ACCEPTED = ("ACCEPTED", "Validé")
    REFUSED = ("REFUSED", "Problème constaté")
    REFUSED_2 = ("REFUSED_2", "Problème constaté (x2)")
