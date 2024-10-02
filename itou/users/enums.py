"""
Enums fields used in User models.
"""

from django.db import models
from django.urls import reverse


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

    @classmethod
    def get_login_url(cls, user_kind, default="login:job_seeker"):
        url_lookup = {
            UserKind.JOB_SEEKER: "login:job_seeker",
            UserKind.PRESCRIBER: "login:prescriber",
            UserKind.EMPLOYER: "login:employer",
            UserKind.LABOR_INSPECTOR: "login:labor_inspector",
            UserKind.ITOU_STAFF: "login:job_seeker",
        }
        return reverse(url_lookup[user_kind]) if user_kind in url_lookup else reverse(default)


MATOMO_ACCOUNT_TYPE = {
    UserKind.PRESCRIBER: "prescripteur",
    UserKind.EMPLOYER: "employeur inclusif",
}


class Title(models.TextChoices):
    M = "M", "Monsieur"
    MME = "MME", "Madame"


class IdentityProvider(models.TextChoices):
    DJANGO = "DJANGO", "Django"
    FRANCE_CONNECT = "FC", "FranceConnect"
    INCLUSION_CONNECT = "IC", "Inclusion Connect"
    PRO_CONNECT = "PC", "ProConnect"
    PE_CONNECT = "PEC", "Pôle emploi Connect"

    @classmethod
    @property
    def supported_user_kinds(cls):
        return {
            cls.DJANGO: tuple(UserKind.values),
            cls.FRANCE_CONNECT: (UserKind.JOB_SEEKER,),
            cls.INCLUSION_CONNECT: (UserKind.PRESCRIBER, UserKind.EMPLOYER),
            cls.PE_CONNECT: (UserKind.JOB_SEEKER,),
            cls.PRO_CONNECT: (UserKind.PRESCRIBER, UserKind.EMPLOYER),
        }


class LackOfNIRReason(models.TextChoices):
    TEMPORARY_NUMBER = "TEMPORARY_NUMBER", "Numéro temporaire (NIA/NTT)"
    NO_NIR = "NO_NIR", "Pas de numéro de sécurité sociale"
    NIR_ASSOCIATED_TO_OTHER = (
        "NIR_ASSOCIATED_TO_OTHER",
        "Le numéro de sécurité sociale est associé à quelqu'un d'autre",
    )


class LackOfPoleEmploiId(models.TextChoices):
    REASON_FORGOTTEN = "FORGOTTEN", "Identifiant France Travail oublié"
    REASON_NOT_REGISTERED = "NOT_REGISTERED", "Non inscrit auprès de France Travail"
