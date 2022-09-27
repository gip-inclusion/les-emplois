"""
Enums fields used in User models.
"""

from django.db import models


KIND_JOB_SEEKER = "job_seeker"
KIND_PRESCRIBER = "prescriber"
KIND_SIAE_STAFF = "siae_staff"
KIND_LABOR_INSPECTOR = "labor_inspector"


# TODO(alaurent) Replace all uses of KIND_XXX with this new enum
class Kind(models.TextChoices):
    JOB_SEEKER = KIND_JOB_SEEKER, "candidat"
    PRESCREIBER = KIND_PRESCRIBER, "prescripteur"
    SIAE_STAFF = KIND_SIAE_STAFF, "employeur"
    LABOR_INSPECTOR = KIND_LABOR_INSPECTOR, "inspecteur du travail"


class Title(models.TextChoices):
    M = "M", "Monsieur"
    MME = "MME", "Madame"


class IdentityProvider(models.TextChoices):
    DJANGO = "DJANGO", "Django"
    FRANCE_CONNECT = "FC", "FranceConnect"
    INCLUSION_CONNECT = "IC", "Inclusion Connect"
    PE_CONNECT = "PEC", "Pôle emploi Connect"
