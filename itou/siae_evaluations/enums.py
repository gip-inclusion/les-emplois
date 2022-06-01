from django.db import models

from itou.siaes.models import Siae


class EvaluationChosenPercent:
    MIN = 20
    DEFAULT = 30
    MAX = 40


class EvaluationSiaesKind:
    # Siae.KIND_AI will be eligible for Evaluation from 2022
    Evaluable = [Siae.KIND_EI, Siae.KIND_ACI, Siae.KIND_ETTI]


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
    REVIEWED = "REVIEWED"
    ADVERSARIAL_STAGE = "ADVERSARIAL_STAGE"


class EvaluatedAdministrativeCriteriaState(models.TextChoices):
    PENDING = ("PENDING", "En attente")
    ACCEPTED = ("ACCEPTED", "Validé")
    REFUSED = ("REFUSED", "Problème constaté")
