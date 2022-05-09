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
    # one SIAE can be selected in evaluation if it made
    # at least 10 job applications with self-approval
    # during the evaluated period
    MIN = 10

    # whenever one SIAE made more than 20 job applications with self-approval
    # during the evaluated period, only 20 job applications maximum will be
    # added into the evaluation campaign
    MAX = 100
    SELECTION_PERCENTAGE = 20
    SELECTED_MAX = int(MAX * SELECTION_PERCENTAGE / 100)


class EvaluatedJobApplicationsState(models.TextChoices):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    UPLOADED = "UPLOADED"
    SUBMITTED = "SUBMITTED"


class EvaluatedJobApplicationsSelectCriteriaState(models.TextChoices):
    PENDING = "PENDING"
    EDITABLE = "EDITABLE"
    NOTEDITABLE = "NOTEDITABLE"


class EvaluatedSiaeState(models.TextChoices):
    PENDING = "PENDING"
    SUBMITTABLE = "SUBMITTABLE"
    SUBMITTED = "SUBMITTED"
