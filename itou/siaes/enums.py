from django.db import models


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
        # TODO(celinems): move KIND_* to a dedicated enums module.
        from itou.siaes.models import Siae

        choices = None
        # TODO(celinems): Use Python 3.10 match / case syntax when this version will be available on our project.
        if kind == Siae.KIND_GEIQ:
            choices = [cls.APPRENTICESHIP, cls.PROFESSIONAL_TRAINING, cls.OTHER]
        elif kind in [Siae.KIND_EA, Siae.KIND_EATT]:
            choices = [
                cls.PERMANENT,
                cls.FIXED_TERM,
                cls.TEMPORARY,
                cls.FIXED_TERM_TREMPLIN,
                cls.APPRENTICESHIP,
                cls.PROFESSIONAL_TRAINING,
                cls.OTHER,
            ]
        elif kind == Siae.KIND_EITI:
            choices = [cls.BUSINESS_CREATION, cls.OTHER]
        elif kind == Siae.KIND_OPCS:
            choices = [cls.PERMANENT, cls.FIXED_TERM, cls.APPRENTICESHIP, cls.PROFESSIONAL_TRAINING, cls.OTHER]
        elif kind in [Siae.KIND_ACI, Siae.KIND_ACIPHC, Siae.KIND_EI, Siae.KIND_AI, Siae.KIND_ETTI]:
            # Siae.ELIGIBILITY_REQUIRED_KINDS but without EITI.
            choices = [cls.FIXED_TERM_I, cls.FIXED_TERM_USAGE, cls.TEMPORARY, cls.PROFESSIONAL_TRAINING, cls.OTHER]
        else:
            choices = list(cls)

        return cls._choices_from_enums_list(choices)
