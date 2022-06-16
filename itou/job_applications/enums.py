from django.db import models

from itou.users import enums as users_enums


class SenderKind(models.TextChoices):
    JOB_SEEKER = users_enums.KIND_JOB_SEEKER, "Demandeur d'emploi"
    PRESCRIBER = users_enums.KIND_PRESCRIBER, "Prescripteur"
    SIAE_STAFF = users_enums.KIND_SIAE_STAFF, "Employeur (SIAE)"
