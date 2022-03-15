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
