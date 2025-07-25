from django.db import models


class CompanyKind(models.TextChoices):
    ACI = "ACI", "Atelier chantier d'insertion"
    AI = "AI", "Association intermédiaire"
    EA = "EA", "Entreprise adaptée"
    EATT = "EATT", "Entreprise adaptée de travail temporaire"
    EI = "EI", "Entreprise d'insertion"  # Regroupées au sein de la fédération des entreprises d'insertion.
    EITI = "EITI", "Entreprise d'insertion par le travail indépendant"
    ETTI = "ETTI", "Entreprise de travail temporaire d'insertion"
    GEIQ = "GEIQ", "Groupement d'employeurs pour l'insertion et la qualification"
    OPCS = "OPCS", "Organisation porteuse de la clause sociale"

    @classmethod
    def siae_choices(cls):
        """Returns a list of CompanyKinds which are SIAEs."""
        return [(k, v) for k, v in cls.choices if k in cls.siae_kinds()]

    @classmethod
    def siae_kinds(cls):
        return [
            cls.AI.value,
            cls.ACI.value,
            cls.EI.value,
            cls.EITI.value,
            cls.ETTI.value,
        ]


class ContractNature(models.TextChoices):
    PEC_OFFER = "PEC_OFFER", "Contrat PEC - Parcours Emploi Compétences"


class JobSourceTag(models.TextChoices):
    FT_PEC_OFFER = "FT_PEC_OFFER", "Contrat PEC - Parcours Emploi Compétences"


class ContractType(models.TextChoices):
    """
    A list of possible work contract types for Companies.
    Not included as an intern class of JobDescription because of possible reuse cases.
    """

    PERMANENT = "PERMANENT", "CDI"
    PERMANENT_I = "PERMANENT_I", "CDI inclusion"
    FIXED_TERM = "FIXED_TERM", "CDD"
    FIXED_TERM_USAGE = "FIXED_TERM_USAGE", "CDD d'usage"
    FIXED_TERM_I = "FIXED_TERM_I", "CDD insertion"
    FIXED_TERM_I_PHC = "FIXED_TERM_I_PHC", "CDD-I PHC"
    FIXED_TERM_I_CVG = "FIXED_TERM_I_CVG", "CDD-I CVG"
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
    def choices_for_company(cls, company):
        choices = cls.choices_for_company_kind(company.kind)
        if company.is_aci_convergence:
            choices[-1:-1] = cls._choices_from_enums_list(
                [
                    cls.FIXED_TERM_I_PHC,
                    cls.FIXED_TERM_I_CVG,
                ]
            )
        return choices

    @classmethod
    def choices_for_company_kind(cls, kind):
        choices = []

        match kind:
            case CompanyKind.GEIQ:
                choices = [cls.APPRENTICESHIP, cls.PROFESSIONAL_TRAINING, cls.OTHER]
            case CompanyKind.EA | CompanyKind.EATT:
                choices = [
                    cls.PERMANENT,
                    cls.FIXED_TERM,
                    cls.TEMPORARY,
                    cls.FIXED_TERM_TREMPLIN,
                    cls.APPRENTICESHIP,
                    cls.PROFESSIONAL_TRAINING,
                    cls.OTHER,
                ]
            case CompanyKind.EITI:
                choices = [cls.BUSINESS_CREATION, cls.OTHER]
            case CompanyKind.OPCS:
                choices = [cls.PERMANENT, cls.FIXED_TERM, cls.APPRENTICESHIP, cls.PROFESSIONAL_TRAINING, cls.OTHER]
            case CompanyKind.ACI | CompanyKind.EI | CompanyKind.AI | CompanyKind.ETTI:
                # SIAEs, without EITI.
                choices = [cls.FIXED_TERM_I, cls.FIXED_TERM_USAGE, cls.TEMPORARY, cls.PROFESSIONAL_TRAINING, cls.OTHER]
            case _:
                choices = list(cls)
                # These are only for ACI from ACI_CONVERGENCE_SIRET_WHITELIST
                choices.remove(cls.FIXED_TERM_I_PHC)
                choices.remove(cls.FIXED_TERM_I_CVG)

        return cls._choices_from_enums_list(choices)


def siae_kind_to_ft_type_siae(siae_kind):
    # Possible values on Pole Emploi's side:
    # « 836 – IAE ITOU ACI »
    # « 837 – IAE ITOU AI »
    # « 838 – IAE ITOU EI »
    # « 839 – IAE ITOU ETT »
    # « 840 – IAE ITOU EIT »
    return {
        CompanyKind.ACI: 836,
        CompanyKind.AI: 837,
        CompanyKind.EA: 838,
        CompanyKind.EATT: 840,
        CompanyKind.EI: 838,
        CompanyKind.EITI: 840,
        CompanyKind.ETTI: 839,
        CompanyKind.GEIQ: 838,
    }.get(siae_kind)


class JobSource(models.TextChoices):
    PE_API = "PE_API", "API France Travail"


# SIRET of the POLE EMPLOI structure as of January 2023
POLE_EMPLOI_SIRET = "13000548100010"

# Not within the CompanyKind TextChoices, it is a special value reserved for special
# siaes that are managed by the software.
COMPANY_KIND_RESERVED = "RESERVED"

# not in Siae.SOURCE_XXX choices deliberately: this value can't be selected in
# the admin and must be set by software.
COMPANY_SOURCE_ADMIN_CREATED = "ADMIN_CREATED"


class JobDescriptionSource(models.TextChoices):
    MANUALLY = "MANUALLY", "Fiche de poste créée manuellement"
    HIRING = "HIRING", "Fiche de poste créée automatiquement à l'embauche"
