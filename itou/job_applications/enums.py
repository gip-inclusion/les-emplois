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


class RefusalReason(models.TextChoices):
    DID_NOT_COME = "did_not_come", "Candidat non venu ou non joignable"
    UNAVAILABLE = "unavailable", "Candidat indisponible ou non intéressé par le poste"
    NON_ELIGIBLE = "non_eligible", "Candidat non éligible"
    ELIGIBILITY_DOUBT = (
        "eligibility_doubt",
        "Doute sur l'éligibilité du candidat (penser à renvoyer la personne vers un prescripteur)",
    )
    INCOMPATIBLE = "incompatible", "Un des freins à l'emploi du candidat est incompatible avec le poste proposé"
    PREVENT_OBJECTIVES = (
        "prevent_objectives",
        "L'embauche du candidat empêche la réalisation des objectifs du dialogue de gestion",
    )
    NO_POSITION = "no_position", "Pas de poste ouvert en ce moment"
    APPROVAL_EXPIRATION_TOO_CLOSE = (
        "approval_expiration_too_close",
        "La date de fin du PASS IAE / agrément est trop proche",
    )
    DEACTIVATION = "deactivation", "La structure n'est plus conventionnée"
    NOT_MOBILE = "not_mobile", "Candidat non mobile"
    POORLY_INFORMED = "poorly_informed", "Candidature pas assez renseignée"
    OTHER = "other", "Autre"
