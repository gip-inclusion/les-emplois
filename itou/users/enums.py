"""
Enums fields used in User models.
"""

from django.db import models


KIND_JOB_SEEKER = "job_seeker"
KIND_PRESCRIBER = "prescriber"
KIND_EMPLOYER = "employer"
KIND_LABOR_INSPECTOR = "labor_inspector"
KIND_PROFESSIONAL = "professional"
KIND_ITOU_STAFF = "itou_staff"


class UserKind(models.TextChoices):
    JOB_SEEKER = KIND_JOB_SEEKER, "candidat"
    PROFESSIONAL = KIND_PROFESSIONAL, "professionnel"
    ITOU_STAFF = KIND_ITOU_STAFF, "administrateur"


class Title(models.TextChoices):
    M = "M", "Monsieur"
    MME = "MME", "Madame"


class IdentityProvider(models.TextChoices):
    DJANGO = "DJANGO", "Django"
    FRANCE_CONNECT = "FC", "FranceConnect"
    PRO_CONNECT = "PC", "ProConnect"
    PE_CONNECT = "PEC", "France Travail Connect"


IDENTITY_PROVIDER_SUPPORTED_USER_KIND = {
    IdentityProvider.DJANGO: tuple(UserKind.values),
    IdentityProvider.FRANCE_CONNECT: (UserKind.JOB_SEEKER,),
    IdentityProvider.PE_CONNECT: (UserKind.JOB_SEEKER,),
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
    CREATE = "CREATE", "création du compte candidat"
    APPLY = "APPLY", "envoi de candidature"
    HIRE = "HIRE", "déclaration d'embauche"
    ACCEPT = "ACCEPT", "acceptation de candidature"
    IAE_ELIGIBILITY = "IAE_ELIGIBILITY", "validation de l'éligibilité IAE"
    GEIQ_ELIGIBILITY = "GEIQ_ELIGIBILITY", "validation de l'éligibilité GEIQ"
