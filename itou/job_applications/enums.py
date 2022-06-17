from django.db import models

from itou.users import enums as users_enums


class SenderKind(models.TextChoices):
    JOB_SEEKER = users_enums.KIND_JOB_SEEKER, "Demandeur d'emploi"
    PRESCRIBER = users_enums.KIND_PRESCRIBER, "Prescripteur"
    SIAE_STAFF = users_enums.KIND_SIAE_STAFF, "Employeur (SIAE)"


def sender_kind_to_pe_origine_candidature(sender_kind):
    return {
        SenderKind.JOB_SEEKER: "DEMA",
        SenderKind.PRESCRIBER: "PRES",
        SenderKind.SIAE_STAFF: "EMPL",
    }.get(sender_kind, "DEMA")
