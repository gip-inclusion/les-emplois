import enum

from django.db import models


KIND_JOB_SEEKER = "job_seeker"
KIND_PRESCRIBER = "prescriber"
KIND_EMPLOYER = "employer"
KIND_LABOR_INSPECTOR = "labor_inspector"
KIND_PROFESSIONAL = "professional"
KIND_ITOU_STAFF = "itou_staff"


class UserKind(models.TextChoices):
    JOB_SEEKER = KIND_JOB_SEEKER, "usager"
    PROFESSIONAL = KIND_PROFESSIONAL, "professionnel"
    ITOU_STAFF = KIND_ITOU_STAFF, "administrateur"


class Title(models.TextChoices):
    M = "M", "Monsieur"
    MME = "MME", "Madame"


class IdentityProvider(models.TextChoices):
    DJANGO = "DJANGO", "Django"
    FRANCE_CONNECT = "FC", "FranceConnect"
    PRO_CONNECT = "PC", "ProConnect"
    FT_CONNECT = "FTC", "France Travail Connect"


IDENTITY_PROVIDER_SUPPORTED_USER_KIND = {
    IdentityProvider.DJANGO: tuple(UserKind.values),
    IdentityProvider.FRANCE_CONNECT: (UserKind.JOB_SEEKER,),
    IdentityProvider.FT_CONNECT: (UserKind.JOB_SEEKER,),
    IdentityProvider.PRO_CONNECT: (UserKind.PROFESSIONAL,),
}


class IdentityCertificationAuthorities(models.TextChoices):
    API_FT_RECHERCHE_INDIVIDU_CERTIFIE = (
        "api_recherche_individu_certifie",
        "API France Travail recherche individu certifié",
    )
    API_PARTICULIER = "api_particulier", "API Particulier"
    API_FT_RECHERCHER_USAGER = "api_rechercher_usager", "API France Travail rechercher usager"


class LackOfNIRReason(models.TextChoices):
    NO_NIR = "NO_NIR", "Pas de numéro de sécurité sociale"
    NIR_ASSOCIATED_TO_OTHER = (
        "NIR_ASSOCIATED_TO_OTHER",
        "Le numéro de sécurité sociale est associé à quelqu'un d'autre",
    )


class LackOfPoleEmploiId(models.TextChoices):
    REASON_FORGOTTEN = "FORGOTTEN", "Identifiant France Travail oublié"
    REASON_NOT_REGISTERED = "NOT_REGISTERED", "Non inscrit auprès de France Travail"


class ActionKind(models.TextChoices):
    CREATE = "CREATE", "création du compte usager"
    APPLY = "APPLY", "envoi de candidature"
    HIRE = "HIRE", "déclaration d'embauche"
    ACCEPT = "ACCEPT", "acceptation de candidature"
    IAE_ELIGIBILITY = "IAE_ELIGIBILITY", "validation de l'éligibilité IAE"
    GEIQ_ELIGIBILITY = "GEIQ_ELIGIBILITY", "validation de l'éligibilité GEIQ"
    SELF_ASSIGN = "SELF_ASSIGN", "se positionner comme accompagnateur"
    ORIENT = "ORIENT", "orientation vers un service"


class AssignmentEndReason(models.TextChoices):
    AUTOMATIC = "AUTOMATIC", "automatique"
    MANUAL = "MANUAL", "manuel"


class JobSeekerAssignmentDisplayMode(enum.StrEnum):
    ACTIVE_WITH_ORG_AND_MEMBERSHIP = "ACTIVE_WITH_ORG_AND_MEMBERSHIP"
    ACTIVE_WITH_ORG_NO_MEMBERSHIP = "ACTIVE_WITH_ORG_NO_MEMBERSHIP"
    ACTIVE_NO_ORG = "ACTIVE_NO_ORG"
    UNKNOWN_ADVISOR = "UNKNOWN_ADVISOR"
    INACTIVE_WITH_ORG = "INACTIVE_WITH_ORG"
    INACTIVE_NO_ORG = "INACTIVE_NO_ORG"

    # Make the Enum work in Django's templates
    # See :
    # - https://docs.djangoproject.com/en/dev/ref/templates/api/#variables-and-lookups
    # - https://github.com/django/django/pull/12304
    do_not_call_in_templates = enum.nonmember(True)


class ProSupportReportBarrier(models.TextChoices):
    HEALTH = "HEALTH", "Santé"
    MOBILITY = "MOBILITY", "Mobilité"
    FAMILY = "FAMILY", "Situation personnelle ou familiale"
    FINANCIAL = "FINANCIAL", "Situation financière"
    DIGITAL = "DIGITAL", "Situation numérique"
    LEGAL = "LEGAL", "Situation administrative ou juridique"
    LITERACY = "LITERACY", "Situation en français ou en calcul"


class ProSupportReportAutonomy(models.IntegerChoices):
    STEP_BY_STEP = 1, "Il a besoin d’être accompagné à chaque étape (rédaction du CV, identification d’offres…)."
    REGULAR_SUPPORT = 2, "Il a besoin d’un appui régulier pour mener ses démarches à terme."
    OCCASIONAL_SUPPORT = 3, "Il mène la plupart des démarches seul, mais sollicite un accompagnement ponctuel."
    SUPPORT_IF_BLOCKED = 4, "Il est autonome et sollicite l’accompagnement seulement en cas de blocage."
    AUTONOMOUS = 5, "Il est autonome (recherche, candidature, entretien) sans besoin d’accompagnement."


class ProSupportReportSolution(models.TextChoices):
    RENEWAL = "RENEWAL", "Contrat renouvelé dans notre structure"
    LASTING_JOB = "LASTING_JOB", "Emploi durable (CDD de plus de 6 mois, CDI, création d’entreprise)"
    TRANSITIONAL_JOB = "TRANSITIONAL_JOB", "Emploi transitoire (CDD de moins de 6 mois)"
    TRAINING = "TRAINING", "Entrée en formation"
    OTHER = "OTHER", "Autre"


class ProSupportReportOrientation(models.TextChoices):
    SOCIAL = "SOCIAL", "Sociale"
    SOCIO_PROFESSIONAL = "SOCIO_PROFESSIONAL", "Socio-professionnelle"
    PROFESSIONAL = "PROFESSIONAL", "Professionnelle"
    TO_BE_DEFINED = "TO_BE_DEFINED", "À définir avec le prescripteur"
