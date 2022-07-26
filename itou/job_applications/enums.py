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
    DID_NOT_COME = "did_not_come", "Candidat non joignable"
    DID_NOT_COME_TO_INTERVIEW = "did_not_come_to_interview", "Candidat ne s’étant pas présenté à l’entretien"
    HIRED_ELSEWHERE = "hired_elsewhere", "Candidat indisponible : en emploi"
    TRAINING = "training", "Candidat indisponible : en formation"
    NON_ELIGIBLE = "non_eligible", "Candidat non éligible"
    NOT_MOBILE = "not_mobile", "Candidat non mobile"
    NOT_INTERESTED = "not_interested", "Candidat non intéressé"
    LACKING_SKILLS = "lacking_skills", "Le candidat n’a pas les compétences requises pour le poste"
    INCOMPATIBLE = "incompatible", "Un des freins à l'emploi du candidat est incompatible avec le poste proposé"
    PREVENT_OBJECTIVES = (
        "prevent_objectives",
        "L'embauche du candidat empêche la réalisation des objectifs du dialogue de gestion",
    )
    NO_POSITION = "no_position", "Pas de recrutement en cours"
    OTHER = "other", "Autre (détails dans le message ci-dessous)"

    # Hidden reasons kept for history.
    APPROVAL_EXPIRATION_TOO_CLOSE = (
        "approval_expiration_too_close",
        "La date de fin du PASS IAE / agrément est trop proche",
    )
    UNAVAILABLE = "unavailable", "Candidat indisponible ou non intéressé par le poste"
    ELIGIBILITY_DOUBT = (
        "eligibility_doubt",
        "Doute sur l'éligibilité du candidat (penser à renvoyer la personne vers un prescripteur)",
    )
    DEACTIVATION = "deactivation", "La structure n'est plus conventionnée"
    POORLY_INFORMED = "poorly_informed", "Candidature pas assez renseignée"

    @classmethod
    def hidden(cls):
        """Old refusal reasons kept for history but not displayed to end users."""
        return [
            cls.APPROVAL_EXPIRATION_TOO_CLOSE,
            cls.DEACTIVATION,
            cls.ELIGIBILITY_DOUBT,
            cls.UNAVAILABLE,
            cls.POORLY_INFORMED,
        ]

    @classmethod
    def displayed_choices(cls):
        """
        Hide values in forms but don't override self.choices method to keep hidden enums visible in Django admin.
        """
        return [(None, "")] + [(enum.value, enum.label) for enum in cls if enum not in cls.hidden()]
