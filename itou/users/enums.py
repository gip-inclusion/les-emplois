"""
Enums fields used in User models.
"""

from django.db import models


KIND_JOB_SEEKER = "job_seeker"
KIND_PRESCRIBER = "prescriber"
KIND_EMPLOYER = "employer"
KIND_LABOR_INSPECTOR = "labor_inspector"
KIND_ITOU_STAFF = "itou_staff"


class UserKind(models.TextChoices):
    JOB_SEEKER = KIND_JOB_SEEKER, "candidat"
    PRESCRIBER = KIND_PRESCRIBER, "prescripteur"
    EMPLOYER = KIND_EMPLOYER, "employeur"
    LABOR_INSPECTOR = KIND_LABOR_INSPECTOR, "inspecteur du travail"
    ITOU_STAFF = KIND_ITOU_STAFF, "administrateur"


class Title(models.TextChoices):
    M = "M", "Monsieur"
    MME = "MME", "Madame"


class IdentityProvider(models.TextChoices):
    DJANGO = "DJANGO", "Django"
    FRANCE_CONNECT = "FC", "FranceConnect"
    INCLUSION_CONNECT = "IC", "Inclusion Connect"
    PE_CONNECT = "PEC", "Pôle emploi Connect"


class LackOfNIRReason(models.TextChoices):
    TEMPORARY_NUMBER = "TEMPORARY_NUMBER", "Numéro temporaire (NIA/NTT)"
    NO_NIR = "NO_NIR", "Pas de numéro de sécurité sociale"
    NIR_ASSOCIATED_TO_OTHER = (
        "NIR_ASSOCIATED_TO_OTHER",
        "Le numéro de sécurité sociale est associé à quelqu'un d'autre",
    )


class LackOfPoleEmploiId(models.TextChoices):
    REASON_FORGOTTEN = "FORGOTTEN", "Identifiant Pôle emploi oublié"
    REASON_NOT_REGISTERED = "NOT_REGISTERED", "Non inscrit auprès de Pôle emploi"
