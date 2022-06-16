"""
Enums fields used in User models.
"""

from django.db import models


KIND_JOB_SEEKER = "job_seeker"
KIND_PRESCRIBER = "prescriber"
KIND_SIAE_STAFF = "siae_staff"
KIND_LABOR_INSPECTOR = "labor_inspector"


class Title(models.TextChoices):
    M = "M", "Monsieur"
    MME = "MME", "Madame"


class IdentityProvider(models.TextChoices):
    DJANGO = "DJANGO", "Django"
    FRANCE_CONNECT = "FC", "FranceConnect"
    INCLUSION_CONNECT = "IC", "Inclusion Connect"
    PE_CONNECT = "PEC", "Pôle emploi Connect"
