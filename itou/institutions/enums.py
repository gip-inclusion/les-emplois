from django.db import models


class InstitutionKind(models.TextChoices):
    # --- Departemental level.

    DDETS_GEIQ = (
        "DDETS GEIQ",
        "Direction départementale de l'emploi, du travail et des solidarités, division GEIQ",
    )
    DDETS_IAE = (
        "DDETS IAE",
        "Direction départementale de l'emploi, du travail et des solidarités, division IAE",
    )
    DDETS_LOG = (
        "DDETS LOG",
        "Direction départementale de l'emploi, du travail et des solidarités, division logement insertion",
    )

    # --- Regional level.

    DREETS_GEIQ = (
        "DREETS GEIQ",
        "Direction régionale de l'économie, de l'emploi, du travail et des solidarités, division GEIQ",
    )
    DREETS_IAE = (
        "DREETS IAE",
        "Direction régionale de l'économie, de l'emploi, du travail et des solidarités, division IAE",
    )
    # DREETS_LOG do not exist in practice, the DRIHL is like a DREETS_LOG for the IDF region.
    # Other regions do not have a dedicated entity and are managed directly by their DREETS_IAE.
    DRIHL = ("DRIHL", "Direction régionale et interdépartementale de l'Hébergement et du Logement")

    # --- National level.

    DGEFP_GEIQ = ("DGEFP GEIQ", "Délégation générale à l'emploi et à la formation professionnelle, division GEIQ")
    DGEFP_IAE = ("DGEFP IAE", "Délégation générale à l'emploi et à la formation professionnelle, division IAE")
    DIHAL = ("DIHAL", "Délégation interministérielle à l'hébergement et à l'accès au logement")
    IAE_NETWORK = ("Réseau IAE", "Réseau employeur de l'insertion par l'activité économique")
    CONVERGENCE = ("CONVERGENCE", "Convergence France")

    OTHER = ("Autre", "Autre")
