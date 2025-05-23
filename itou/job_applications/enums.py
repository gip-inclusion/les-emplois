import datetime

from django.db import models

from itou.users import enums as users_enums


class JobApplicationState(models.TextChoices):
    NEW = "new", "Nouvelle candidature"
    PROCESSING = "processing", "Candidature à l'étude"
    POSTPONED = "postponed", "Candidature en attente"
    PRIOR_TO_HIRE = "prior_to_hire", "Action préalable à l’embauche"
    ACCEPTED = "accepted", "Candidature acceptée"
    REFUSED = "refused", "Candidature déclinée"
    CANCELLED = "cancelled", "Embauche annulée"
    # When a job application is accepted, all other job seeker's pending applications become obsolete.
    OBSOLETE = "obsolete", "Embauché ailleurs"


ARCHIVABLE_JOB_APPLICATION_STATES = [
    JobApplicationState.NEW,
    JobApplicationState.PROCESSING,
    JobApplicationState.POSTPONED,
    JobApplicationState.REFUSED,
    JobApplicationState.CANCELLED,
    JobApplicationState.OBSOLETE,
]

# States in which an employer can manually archive an application.
# Employers are encouraged to send an answer to job applicants before
# they can archive their applications.
ARCHIVABLE_JOB_APPLICATION_STATES_MANUAL = [
    JobApplicationState.REFUSED,
    JobApplicationState.CANCELLED,
    JobApplicationState.OBSOLETE,
]

AUTO_REJECT_JOB_APPLICATION_STATES = [
    JobApplicationState.NEW,
    JobApplicationState.PROCESSING,
]


class SenderKind(models.TextChoices):
    JOB_SEEKER = users_enums.KIND_JOB_SEEKER, "Demandeur d'emploi"
    PRESCRIBER = users_enums.KIND_PRESCRIBER, "Prescripteur"
    EMPLOYER = users_enums.KIND_EMPLOYER, "Employeur"


def sender_kind_to_pe_origine_candidature(sender_kind):
    return {
        SenderKind.JOB_SEEKER: "DEMA",
        SenderKind.PRESCRIBER: "PRES",
        SenderKind.EMPLOYER: "EMPL",
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
    DUPLICATE = "duplicate", "Candidature en doublon"
    AUTO = "auto", "Refus automatique"
    OTHER = "other", "Autre"

    # Hidden reasons kept for history.
    APPROVAL_EXPIRATION_TOO_CLOSE = (
        "approval_expiration_too_close",
        "La date de fin du PASS IAE / agrément est trop proche",
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
        """Refusal reasons not displayed to end users."""
        return [
            cls.APPROVAL_EXPIRATION_TOO_CLOSE,  # kept for history
            cls.DEACTIVATION,  # kept for history
            cls.ELIGIBILITY_DOUBT,  # kept for history
            cls.UNAVAILABLE,  # kept for history
            cls.POORLY_INFORMED,  # kept for history
            cls.AUTO,
        ]

    @classmethod
    def displayed_choices(cls, extra_exclude_enums=None):
        """
        Hide values in forms but don't override self.choices method to keep hidden enums visible in Django admin.
        """
        empty = [(None, cls.__empty__)] if hasattr(cls, "__empty__") else []
        excluded_enums = cls.hidden()
        if extra_exclude_enums:
            excluded_enums += extra_exclude_enums
        return empty + [(enum.value, enum.label) for enum in cls if enum not in excluded_enums]


class Origin(models.TextChoices):
    DEFAULT = "default", "Créée normalement via les emplois"
    PE_APPROVAL = "pe_approval", "Créée lors d'un import d'Agrément Pole Emploi"
    # On November 30th, 2021, AI were delivered approvals without a diagnosis.
    AI_STOCK = "ai_stock", "Créée lors de l'import du stock AI"
    ADMIN = "admin", "Créée depuis l'admin"


class ProfessionalSituationExperience(models.TextChoices):
    PMSMP = "PROFESSIONAL_SITUATION_EXPERIENCE_PMSMP", "PMSMP"
    MRS = "PROFESSIONAL_SITUATION_EXPERIENCE_MRS", "MRS"
    STAGE = "PROFESSIONAL_SITUATION_EXPERIENCE_STAGE", "STAGE"
    OTHER = "PROFESSIONAL_SITUATION_EXPERIENCE_OTHER", "Autre"


class Prequalification(models.TextChoices):
    LOCAL_PLAN = "PREQUALIFICATION_LOCAL_PLAN", "Dispositif régional ou sectoriel"
    AFPR = "PREQUALIFICATION_AFPR", "AFPR"
    POE = "PREQUALIFICATION_POE", "POE"
    OTHER = "PREQUALIFICATION_OTHER", "Autre"


class QualificationType(models.TextChoices):
    STATE_DIPLOMA = "STATE_DIPLOMA", "Diplôme d'état ou titre homologué"
    CQP = "CQP", "CQP"
    CCN = "CCN", "Positionnement de CCN"


class QualificationLevel(models.TextChoices):
    LEVEL_3 = "LEVEL_3", "Niveau 3 (CAP, BEP)"
    LEVEL_4 = "LEVEL_4", "Niveau 4 (BP, Bac général, Techno ou Pro, BT)"
    LEVEL_5 = "LEVEL_5", "Niveau 5 ou + (Bac+2 ou +)"
    NOT_RELEVANT = "NOT_RELEVANT", "Non concerné"


GEIQ_MIN_HOURS_PER_WEEK = 1
GEIQ_MAX_HOURS_PER_WEEK = 48

AUTO_REJECT_JOB_APPLICATION_DELAY = datetime.timedelta(days=60)
