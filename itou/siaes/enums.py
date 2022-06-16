from django.db import models


class SiaeKind(models.TextChoices):

    EI = "EI", "Entreprise d'insertion"  # Regroupées au sein de la fédération des entreprises d'insertion.
    AI = "AI", "Association intermédiaire"
    ACI = "ACI", "Atelier chantier d'insertion"

    # When an ACI does PHC ("Premières Heures en Chantier"), we have both an ACI created by
    # the SIAE ASP import (plus its ACI antenna) and an ACIPHC created by our staff (plus its ACIPHC antenna).
    # The first one is managed by ASP data, the second one is managed by our staff.
    ACIPHC = "ACIPHC", "Atelier chantier d'insertion premières heures en chantier"

    ETTI = "ETTI", "Entreprise de travail temporaire d'insertion"
    EITI = "EITI", "Entreprise d'insertion par le travail indépendant"
    GEIQ = "GEIQ", "Groupement d'employeurs pour l'insertion et la qualification"
    EA = "EA", "Entreprise adaptée"
    EATT = "EATT", "Entreprise adaptée de travail temporaire"
    OPCS = "OPCS", "Organisation porteuse de la clause sociale"


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
    def choices_from_siae_kind(cls, kind):
        choices = None
        # TODO(celinems): Use Python 3.10 match / case syntax when this version will be available on our project.
        if kind == SiaeKind.GEIQ:
            choices = [cls.APPRENTICESHIP, cls.PROFESSIONAL_TRAINING, cls.OTHER]
        elif kind in [SiaeKind.EA, SiaeKind.EATT]:
            choices = [
                cls.PERMANENT,
                cls.FIXED_TERM,
                cls.TEMPORARY,
                cls.FIXED_TERM_TREMPLIN,
                cls.APPRENTICESHIP,
                cls.PROFESSIONAL_TRAINING,
                cls.OTHER,
            ]
        elif kind == SiaeKind.EITI:
            choices = [cls.BUSINESS_CREATION, cls.OTHER]
        elif kind == SiaeKind.OPCS:
            choices = [cls.PERMANENT, cls.FIXED_TERM, cls.APPRENTICESHIP, cls.PROFESSIONAL_TRAINING, cls.OTHER]
        elif kind == SiaeKind.ACI:
            choices = [
                cls.FIXED_TERM_I,
                cls.FIXED_TERM_USAGE,
                cls.TEMPORARY,
                cls.PROFESSIONAL_TRAINING,
                cls.FIXED_TERM_I_PHC,
                cls.FIXED_TERM_I_CVG,
                cls.OTHER,
            ]
        elif kind in [SiaeKind.ACIPHC, SiaeKind.EI, SiaeKind.AI, SiaeKind.ETTI]:
            # Siae.ELIGIBILITY_REQUIRED_KINDS but without EITI.
            choices = [cls.FIXED_TERM_I, cls.FIXED_TERM_USAGE, cls.TEMPORARY, cls.PROFESSIONAL_TRAINING, cls.OTHER]
        else:
            choices = list(cls)

        return cls._choices_from_enums_list(choices)
