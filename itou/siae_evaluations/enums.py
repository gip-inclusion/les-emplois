from django.db import models

from itou.companies.enums import CompanyKind


class EvaluationChosenPercent:
    MIN = 20
    DEFAULT = 30
    MAX = 40


class EvaluationSiaesKind:
    Evaluable = [CompanyKind.AI, CompanyKind.EI, CompanyKind.ACI, CompanyKind.ETTI]


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


EVALUATED_JOB_APPLICATIONS_SANCTIONNABLE_STATES = [
    # None of the criteria have been selected for justification
    EvaluatedJobApplicationsState.PENDING,
    # The criteria have been selected but no proof have been uploaded
    EvaluatedJobApplicationsState.PROCESSING,
    # The proofs have been uploaded for each selected criterion, but not submitted for validation
    EvaluatedJobApplicationsState.UPLOADED,
    # The justification has been refused the first time
    EvaluatedJobApplicationsState.REFUSED,
    # The justification has been refused a second time during the adversarial stage
    EvaluatedJobApplicationsState.REFUSED_2,
]


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


class EvaluatedSiaeFinalState(models.TextChoices):
    ACCEPTED = EvaluatedSiaeState.ACCEPTED.value
    REFUSED = EvaluatedSiaeState.REFUSED.value


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
