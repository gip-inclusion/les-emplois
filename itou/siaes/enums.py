from django.conf import settings
from django.db import models


class SiaeKind(models.TextChoices):
    EI = "EI", "Entreprise d'insertion"  # Regroupées au sein de la fédération des entreprises d'insertion.
    AI = "AI", "Association intermédiaire"
    ACI = "ACI", "Atelier chantier d'insertion"
    ETTI = "ETTI", "Entreprise de travail temporaire d'insertion"
    EITI = "EITI", "Entreprise d'insertion par le travail indépendant"
    GEIQ = "GEIQ", "Groupement d'employeurs pour l'insertion et la qualification"
    EA = "EA", "Entreprise adaptée"
    EATT = "EATT", "Entreprise adaptée de travail temporaire"
    OPCS = "OPCS", "Organisation porteuse de la clause sociale"


# This used to be the ASP_MANAGED_KINDS list in siaes.models; but it's clearer to talk about
# SIAEs that have a convention.
# Ported older comment: ASP data is used to keep the siae data of these kinds in sync.
# These kinds and only these kinds thus have convention/AF logic.
SIAE_WITH_CONVENTION_KINDS = [
    SiaeKind.EI.value,
    SiaeKind.AI.value,
    SiaeKind.ACI.value,
    SiaeKind.ETTI.value,
    SiaeKind.EITI.value,
]

SIAE_WITH_CONVENTION_CHOICES = [(k, v) for k, v in SiaeKind.choices if k in SIAE_WITH_CONVENTION_KINDS]


class ContractType(models.TextChoices):
    """
    A list of possible work contract types for SIAE.
    Not included as an intern class of SiaeJobDescription because of possible reuse cases.
    """

    PERMANENT = "PERMANENT", "CDI"
    PERMANENT_I = "PERMANENT_I", "CDI inclusion"
    FIXED_TERM = "FIXED_TERM", "CDD"
    FIXED_TERM_USAGE = "FIXED_TERM_USAGE", "CDD d'usage"
    FIXED_TERM_I = "FIXED_TERM_I", "CDD insertion"
    FIXED_TERM_I_PHC = "FED_TERM_I_PHC", "CDD-I Premières heures en Chantier"
    FIXED_TERM_I_CVG = "FIXED_TERM_I_CVG", "CDD-I Convergence"
    FIXED_TERM_TREMPLIN = "FIXED_TERM_TREMPLIN", "CDD Tremplin"
    APPRENTICESHIP = "APPRENTICESHIP", "Contrat d'apprentissage"
    PROFESSIONAL_TRAINING = "PROFESSIONAL_TRAINING", "Contrat de professionalisation"
    TEMPORARY = "TEMPORARY", "Contrat de mission intérimaire"
    BUSINESS_CREATION = "BUSINESS_CREATION", "Accompagnement à la création d'entreprise"
    OTHER = "OTHER", "Autre type de contrat"

    @classmethod
    def _choices_from_enums_list(cls, enums):
        # Inspired from django.db.models.eums.ChoicesMeta.choices
        empty = [(None, cls.__empty__)] if hasattr(cls, "__empty__") else []
        return empty + [(enum.value, enum.label) for enum in enums]

    @classmethod
    def choices_for_siae(cls, siae):
        choices = None

        match siae.kind:
            case SiaeKind.GEIQ:
                choices = [cls.APPRENTICESHIP, cls.PROFESSIONAL_TRAINING, cls.OTHER]
            case SiaeKind.EA | SiaeKind.EATT:
                choices = [
                    cls.PERMANENT,
                    cls.FIXED_TERM,
                    cls.TEMPORARY,
                    cls.FIXED_TERM_TREMPLIN,
                    cls.APPRENTICESHIP,
                    cls.PROFESSIONAL_TRAINING,
                    cls.OTHER,
                ]
            case SiaeKind.EITI:
                choices = [cls.BUSINESS_CREATION, cls.OTHER]
            case SiaeKind.OPCS:
                choices = [cls.PERMANENT, cls.FIXED_TERM, cls.APPRENTICESHIP, cls.PROFESSIONAL_TRAINING, cls.OTHER]
            case SiaeKind.ACI | SiaeKind.EI | SiaeKind.AI | SiaeKind.ETTI:
                # SIAE_WITH_CONVENTION_KINDS but without EITI.
                choices = [cls.FIXED_TERM_I, cls.FIXED_TERM_USAGE, cls.TEMPORARY, cls.PROFESSIONAL_TRAINING, cls.OTHER]
            case _:
                choices = list(cls)
                # These are only for ACI from ACI_CONVERGENCE_SIRET_WHITELIST
                choices.remove(cls.FIXED_TERM_I_PHC)
                choices.remove(cls.FIXED_TERM_I_CVG)

        if siae.kind == SiaeKind.ACI and siae.siret in settings.ACI_CONVERGENCE_SIRET_WHITELIST:
            choices[-1:-1] = [
                cls.FIXED_TERM_I_PHC,
                cls.FIXED_TERM_I_CVG,
            ]

        return cls._choices_from_enums_list(choices)


def siae_kind_to_pe_type_siae(siae_kind):
    # Possible values on Pole Emploi's side:
    # « 836 – IAE ITOU ACI »
    # « 837 – IAE ITOU AI »
    # « 838 – IAE ITOU EI »
    # « 839 – IAE ITOU ETT »
    # « 840 – IAE ITOU EIT »
    return {
        SiaeKind.EI: 838,
        SiaeKind.AI: 837,
        SiaeKind.ACI: 836,
        SiaeKind.ETTI: 839,
        SiaeKind.EITI: 840,
        SiaeKind.GEIQ: 838,
        SiaeKind.EA: 838,
        SiaeKind.EATT: 840,
    }.get(siae_kind)
